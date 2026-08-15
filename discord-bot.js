#!/usr/bin/env node
// -*- coding: utf-8 -*-
/**
 * 달무리 디스코드 봇
 *
 * dalmuti.js의 카드 규칙 로직(Player/AIPlayer 등)을 그대로 재사용하고,
 * 콘솔 입출력 대신 디스코드 버튼/드롭다운으로 진행합니다.
 *
 * 실행 전 준비:
 *   1. npm install
 *   2. discord-config.example.json 을 discord-config.json 으로 복사 후 token/clientId 입력
 *   3. node discord-bot.js
 *   4. 디스코드 채널에서 /달무리 입력
 */

const fs = require("fs");
const path = require("path");
const {
  Client,
  GatewayIntentBits,
  Events,
  SlashCommandBuilder,
  REST,
  Routes,
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  StringSelectMenuBuilder,
  EmbedBuilder,
  MessageFlags,
} = require("discord.js");

const { createDeck, shuffle, getTitle, Player, AIPlayer } = require("./dalmuti.js");
const Spl = require("./splendor.js");

const TURN_TIMEOUT_MS = 30 * 1000; // 카드 내기/패스/카드교환 제한시간 (30초)
const CONTINUE_TIMEOUT_MS = 5 * 60 * 1000; // 다음 라운드 진행 여부 제한시간
const SPLENDOR_TURN_TIMEOUT_MS = 45 * 1000; // 스플렌더 턴 제한시간 (45초)

// ════════════════════════════════════════
// 설정 로드
// ════════════════════════════════════════

const CONFIG_PATH = path.join(__dirname, "discord-config.json");
if (!fs.existsSync(CONFIG_PATH)) {
  console.error(
    "discord-config.json 파일이 없습니다.\n" +
      "discord-config.example.json을 복사해서 discord-config.json을 만들고 token/clientId를 입력해주세요."
  );
  process.exit(1);
}
const config = JSON.parse(fs.readFileSync(CONFIG_PATH, "utf8"));
if (!config.token || !config.clientId) {
  console.error("discord-config.json 에 token과 clientId를 모두 입력해주세요.");
  process.exit(1);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ════════════════════════════════════════
// 상태 (채널 단위)
// ════════════════════════════════════════

const lobbies = new Map(); // channelId -> lobby
const games = new Map(); // channelId -> game

const splendorLobbies = new Map(); // channelId -> lobby
const splendorGames = new Map(); // channelId -> game

// ════════════════════════════════════════
// 로비(참가자 모집)
// ════════════════════════════════════════

function estimatedDeckSize(maxRank) {
  let size = 2; // 조커 2장
  for (let r = 1; r <= maxRank; r++) size += r;
  return size;
}

function buildLobbyEmbed(lobby) {
  const names = [...lobby.players.values()].map((p) => `🙂 ${p.username}`).join("\n") || "-";
  const aiCount = Math.max(0, lobby.total - lobby.players.size);
  const deckSize = estimatedDeckSize(lobby.maxRank);
  const perPlayer = Math.floor(deckSize / lobby.total);
  return new EmbedBuilder()
    .setTitle("🎴 달무리 - 참가자 모집")
    .setColor(0x57f287)
    .setDescription(
      `아래 **참가하기** 버튼을 눌러 참여하세요.\n호스트(<@${lobby.hostId}>)가 **게임 시작**을 누르면 시작합니다.`
    )
    .addFields(
      { name: `참가자 (${lobby.players.size}명)`, value: names },
      {
        name: "총 인원",
        value: `${lobby.total}명 (사람 ${lobby.players.size}명 + 부족한 자리는 AI ${aiCount}명이 채웁니다)`,
      },
      {
        name: "카드 숫자 범위",
        value: `1 ~ ${lobby.maxRank} (+조커 2장) — 1인당 약 ${perPlayer}장`,
      }
    );
}

function buildLobbyComponents(lobby) {
  const totalSelect = new StringSelectMenuBuilder()
    .setCustomId("lobby_total")
    .setPlaceholder(`총 인원: ${lobby.total}명 (호스트만 변경 가능)`)
    .addOptions([4, 5, 6, 7, 8].map((n) => ({ label: `${n}명`, value: String(n), default: n === lobby.total })));
  const maxRankSelect = new StringSelectMenuBuilder()
    .setCustomId("lobby_maxrank")
    .setPlaceholder(`카드 숫자 범위: 1~${lobby.maxRank} (호스트만 변경 가능)`)
    .addOptions(
      [6, 7, 8, 9, 10, 11, 12].map((n) => ({
        label: `1~${n} (${n === 12 ? "기본" : "적게"}, 1인당 약 ${Math.floor(estimatedDeckSize(n) / lobby.total)}장)`,
        value: String(n),
        default: n === lobby.maxRank,
      }))
    );
  const row1 = new ActionRowBuilder().addComponents(totalSelect);
  const row2 = new ActionRowBuilder().addComponents(maxRankSelect);
  const row3 = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId("lobby_join").setLabel("참가하기").setStyle(ButtonStyle.Success),
    new ButtonBuilder().setCustomId("lobby_leave").setLabel("나가기").setStyle(ButtonStyle.Secondary),
    new ButtonBuilder().setCustomId("lobby_start").setLabel("게임 시작").setStyle(ButtonStyle.Primary)
  );
  return [row1, row2, row3];
}

async function refreshLobby(interaction, lobby) {
  await interaction.update({ embeds: [buildLobbyEmbed(lobby)], components: buildLobbyComponents(lobby) });
}

async function lobbyJoin(interaction) {
  const lobby = lobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (lobby.players.size >= 8) {
    return interaction.reply({ content: "최대 8명까지 참가할 수 있습니다.", flags: MessageFlags.Ephemeral });
  }
  lobby.players.set(interaction.user.id, { id: interaction.user.id, username: interaction.user.username });
  if (lobby.players.size > lobby.total) lobby.total = lobby.players.size;
  await refreshLobby(interaction, lobby);
}

async function lobbyLeave(interaction) {
  const lobby = lobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (interaction.user.id === lobby.hostId) {
    return interaction.reply({
      content: "호스트는 나갈 수 없습니다. 모집을 취소하려면 관리자에게 메시지 삭제를 요청하세요.",
      flags: MessageFlags.Ephemeral,
    });
  }
  lobby.players.delete(interaction.user.id);
  await refreshLobby(interaction, lobby);
}

async function lobbySetTotal(interaction) {
  const lobby = lobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (interaction.user.id !== lobby.hostId) {
    return interaction.reply({ content: "호스트만 인원 수를 바꿀 수 있습니다.", flags: MessageFlags.Ephemeral });
  }
  const val = parseInt(interaction.values[0]);
  lobby.total = Math.max(val, lobby.players.size, 4);
  await refreshLobby(interaction, lobby);
}

async function lobbySetMaxRank(interaction) {
  const lobby = lobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (interaction.user.id !== lobby.hostId) {
    return interaction.reply({ content: "호스트만 카드 숫자 범위를 바꿀 수 있습니다.", flags: MessageFlags.Ephemeral });
  }
  lobby.maxRank = parseInt(interaction.values[0]);
  await refreshLobby(interaction, lobby);
}

async function lobbyStart(interaction) {
  const lobby = lobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (interaction.user.id !== lobby.hostId) {
    return interaction.reply({ content: "호스트만 게임을 시작할 수 있습니다.", flags: MessageFlags.Ephemeral });
  }

  lobbies.delete(interaction.channelId);
  await interaction.update({ embeds: [buildLobbyEmbed(lobby)], components: [] });

  const players = [];
  for (const p of lobby.players.values()) {
    const pl = new Player(p.username, true);
    pl.discordId = p.id;
    players.push(pl);
  }
  const aiCount = Math.max(0, lobby.total - players.length);
  for (let i = 0; i < aiCount; i++) players.push(new AIPlayer(`AI-${i + 1}`));
  shuffle(players); // 사람이 항상 먼저 나오지 않도록 순서(자리)를 섞음

  const game = {
    channel: lobby.channel,
    hostId: lobby.hostId,
    players,
    maxRank: lobby.maxRank,
    roundNum: 0,
    rankings: [],
    scores: {},
    finishedPlayers: [],
    pending: null,
    statusMessage: null,
    log: [],
  };
  for (const p of players) game.scores[p.name] = 0;
  games.set(interaction.channelId, game);

  runGame(game).catch((err) => {
    console.error(err);
    game.channel.send("⚠️ 게임 중 오류가 발생하여 게임을 종료합니다.").catch(() => {});
    games.delete(interaction.channelId);
  });
}

// ════════════════════════════════════════
// 대기(입력) 헬퍼
// ════════════════════════════════════════

/** 특정 플레이어의 행동을 기다림. 시간 초과 시 onTimeout() 결과로 자동 진행 */
function waitForPlayerAction(game, player, kind, data, onTimeout, timeoutMs = TURN_TIMEOUT_MS) {
  return new Promise((resolve) => {
    let done = false;
    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      game.pending = null;
      resolve(onTimeout ? onTimeout() : null);
    }, timeoutMs);

    game.pending = {
      playerId: player.discordId,
      player,
      kind,
      data,
      deadline: Date.now() + timeoutMs,
      resolve: (val) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        game.pending = null;
        resolve(val);
      },
    };
  });
}

function waitForHostChoice(game) {
  return new Promise((resolve) => {
    let done = false;
    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      game.pending = null;
      resolve(false);
    }, CONTINUE_TIMEOUT_MS);

    game.pending = {
      playerId: game.hostId,
      kind: "continue",
      deadline: Date.now() + CONTINUE_TIMEOUT_MS,
      resolve: (val) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        game.pending = null;
        resolve(val);
      },
    };
  });
}

function logEvent(game, text) {
  game.log.push(text);
}

/** 랭크 숫자를 색깔 있는 뱃지로 표시 (카드 이름은 생략, 숫자만) */
function cardBadge(rank, color) {
  const symbol = rank === 13 ? "★" : rank;
  return `${color}[${symbol}]${ANSI.reset}`;
}

function ansiBlock(text) {
  return "```ansi\n" + text + "\n```";
}

/**
 * 턴 행동 창에 항상 같이 보여줄 손패 요약 (별도 "내 패 보기" 없이도 확인 가능하도록).
 * validRanks가 주어지면 그 숫자만 초록색(지금 낼 수 있음)으로, 나머지는 흐리게 표시.
 * validRanks가 null이면 전부 낼 수 있는 상황(선 낼 때, 카드 교환 등)이므로 전부 초록색으로 표시.
 */
function formatHandLines(player, validRanks = null) {
  const counts = player.counts();
  const ranks = Object.keys(counts).map(Number).sort((a, b) => a - b);
  const lines = ranks.map((r) => {
    const color = r === 13 ? ANSI.boldMagenta : validRanks === null || validRanks.has(r) ? ANSI.boldGreen : ANSI.dim;
    return `${cardBadge(r, color)} × ${counts[r]}장`;
  });
  return `**내 패** (${player.hand.length}장)\n` + ansiBlock(lines.join("\n"));
}

function autoPickGiveIndices(player, count) {
  const hand = player.hand;
  const used = new Set();
  const indices = [];
  for (let i = 0; i < count; i++) {
    let bestIdx = -1;
    for (let j = 0; j < hand.length; j++) {
      if (used.has(j)) continue;
      if (hand[j] !== 13 && (bestIdx === -1 || hand[j] > hand[bestIdx])) bestIdx = j;
    }
    if (bestIdx === -1) {
      for (let j = 0; j < hand.length; j++) {
        if (!used.has(j)) {
          bestIdx = j;
          break;
        }
      }
    }
    if (bestIdx !== -1) {
      used.add(bestIdx);
      indices.push(bestIdx);
    }
  }
  return indices;
}

/** AI(또는 시간초과)가 제한된 후보 인덱스 중에서 count장을 고름. 조커가 아닌 강한 카드 우선 */
function autoPickFromIndices(player, allowedIndices, count) {
  const hand = player.hand;
  const candidates = [...allowedIndices];
  const chosen = [];
  for (let i = 0; i < count && candidates.length > 0; i++) {
    let bestPos = -1;
    for (let j = 0; j < candidates.length; j++) {
      const idx = candidates[j];
      if (hand[idx] !== 13 && (bestPos === -1 || hand[idx] > hand[candidates[bestPos]])) bestPos = j;
    }
    if (bestPos === -1) bestPos = 0;
    chosen.push(candidates[bestPos]);
    candidates.splice(bestPos, 1);
  }
  return chosen;
}

/**
 * 카드 교환으로 받았거나/뺏긴 카드를 나중에 "카드 교환 확인" 버튼으로
 * 대화방에서 비공개(ephemeral)로 볼 수 있도록 기록.
 * DM은 사용하지 않음 - 채널의 버튼을 눌러야만 본인만 볼 수 있는 답으로 표시됨.
 */
function recordExchangeInfo(game, player, { given, received } = {}) {
  if (player instanceof AIPlayer || !player.discordId) return;
  if ((!given || given.length === 0) && (!received || received.length === 0)) return;
  if (!game.exchangeInfo) game.exchangeInfo = new Map();
  const entry = game.exchangeInfo.get(player.discordId) || { given: [], received: [] };
  if (given) entry.given.push(...given);
  if (received) entry.received.push(...received);
  game.exchangeInfo.set(player.discordId, entry);
}

// ════════════════════════════════════════
// 화면(상태 메시지) 렌더링
// ════════════════════════════════════════

// 디스코드 "ansi" 코드블록에서 지원하는 색상 (데스크톱 클라이언트에서 실제 색으로 렌더링됨)
const ANSI = {
  reset: "[0m",
  bold: "[1m",
  dim: "[2m",
  boldYellow: "[1;33m",
  boldGreen: "[1;32m",
  boldCyan: "[1;36m",
  boldMagenta: "[1;35m",
};

function buildPublicEmbed(game, opts = {}) {
  const n = game.players.length;
  const lines = [];
  for (let i = 0; i < n; i++) {
    const p = game.players[i];
    const isAI = p instanceof AIPlayer;
    const tag = isAI ? "🤖" : "🙂";
    const isCurrent = opts.currentIdx === i;
    const status = p.finished ? `✅ ${getTitle(p.finishOrder, n)}` : `카드 ${p.hand.length}장`;
    if (isCurrent) {
      lines.push(`${ANSI.boldGreen}▶ ${tag} ${p.name} — ${status}  (지금 차례!)${ANSI.reset}`);
    } else if (p.finished) {
      lines.push(`${ANSI.dim}${tag} ${p.name} — ${status}${ANSI.reset}`);
    } else {
      lines.push(`${tag} ${p.name} — ${status}`);
    }
  }

  const embed = new EmbedBuilder()
    .setTitle(`🎴 달무리 - 라운드 ${game.roundNum}`)
    .setColor(0x5865f2)
    .addFields({ name: "플레이어", value: ansiBlock(lines.join("\n")) });

  if (opts.tableRank !== undefined && opts.tableRank !== null) {
    const cardText = `${cardBadge(opts.tableRank, ANSI.boldYellow)} × ${opts.tableCount}장`;
    const tableBlock = `${cardText}\n${ANSI.dim}낸 사람:${ANSI.reset} ${ANSI.boldCyan}${opts.tablePlayerName}${ANSI.reset}`;
    embed.addFields({ name: "🃏 바닥 (현재 낼 기준)", value: ansiBlock(tableBlock) });
  } else {
    embed.addFields({ name: "🃏 바닥 (현재 낼 기준)", value: ansiBlock(`${ANSI.dim}비어있음 (선)${ANSI.reset}`) });
  }

  if (game.log.length > 0) {
    embed.addFields({ name: "진행 로그 (이번 트릭)", value: ansiBlock(game.log.slice(-10).join("\n").slice(0, 1000)) });
  }

  if (game.pending && game.pending.deadline) {
    const sec = Math.round(game.pending.deadline / 1000);
    embed.addFields({
      name: "⏰ 제한시간",
      value: `<t:${sec}:R> 까지 응답이 없으면 자동으로 진행됩니다.`,
    });
  }
  return embed;
}

/** 턴 종류에 맞는 버튼 행을 만듦. 누를 게 없으면 null (빈 ActionRow는 디스코드가 거부함) */
function buildActionRow(turnKind) {
  const row = new ActionRowBuilder();
  if (turnKind === "continue") {
    row.addComponents(
      new ButtonBuilder().setCustomId("cont_yes").setLabel("다음 라운드").setStyle(ButtonStyle.Success),
      new ButtonBuilder().setCustomId("cont_no").setLabel("게임 종료").setStyle(ButtonStyle.Danger)
    );
    return row;
  }
  if (turnKind) {
    const label = turnKind === "give" ? "카드 선택하기" : "카드 내기";
    row.addComponents(new ButtonBuilder().setCustomId("act_play").setLabel(label).setStyle(ButtonStyle.Primary));
    if (turnKind === "follow") {
      row.addComponents(new ButtonBuilder().setCustomId("act_pass").setLabel("패스").setStyle(ButtonStyle.Secondary));
    }
    return row;
  }
  return null;
}

/** 이번 라운드 카드 교환 내역(받은/뺏긴 카드)이 있으면, 대화방에서 눌러 비공개로 확인할 수 있는 버튼 행 */
function exchangeCheckRow(game) {
  if (!game.exchangeInfo || game.exchangeInfo.size === 0) return null;
  return new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId("check_exchange").setLabel("카드 교환 확인").setStyle(ButtonStyle.Secondary)
  );
}

async function postStatus(game, embed, rows) {
  const payload = { embeds: [embed], components: rows };
  const prevMessage = game.statusMessage;
  game.statusMessage = await game.channel.send(payload);
  if (prevMessage) {
    // 이전 상태 메시지는 버튼을 없애서 더 이상 누를 수 없게 함 (최신 메시지만 조작 가능)
    prevMessage.edit({ components: [] }).catch(() => {});
  }
}

async function postLog(game, opts = {}) {
  const rows = [buildActionRow(null), exchangeCheckRow(game)].filter(Boolean);
  await postStatus(game, buildPublicEmbed(game, opts), rows);
}

async function showTurn(game, currentIdx, tableRank, tableCount, tablePlayerName, turnKind) {
  const embed = buildPublicEmbed(game, { currentIdx, tableRank, tableCount, tablePlayerName });
  const rows = [buildActionRow(turnKind), exchangeCheckRow(game)].filter(Boolean);
  await postStatus(game, embed, rows);
}

// ════════════════════════════════════════
// 사람 입력을 여는 select 메뉴들 (버튼 클릭 시 호출)
// ════════════════════════════════════════

async function openLeadRankSelect(interaction, game) {
  const player = game.pending.player;
  const counts = player.counts();
  const jokers = counts[13] || 0;
  const ranks = Object.keys(counts)
    .map(Number)
    .filter((r) => r !== 13)
    .sort((a, b) => a - b);

  if (ranks.length === 0) {
    // 조커만 남은 경우 자동 처리
    await interaction.reply({ content: `조커만 남아 자동으로 냅니다.`, flags: MessageFlags.Ephemeral });
    game.pending.resolve({ rank: 12, count: jokers, jokerCount: jokers });
    return;
  }

  const options = ranks.map((r) => ({
    label: `[${r}] × ${counts[r]}장`,
    description: `보유 ${counts[r]}장${jokers > 0 ? ` (+조커 ${jokers}장 사용 가능)` : ""}`,
    value: String(r),
  }));
  const select = new StringSelectMenuBuilder()
    .setCustomId("sel_lead_rank")
    .setPlaceholder("낼 카드 숫자를 선택하세요")
    .addOptions(options.slice(0, 25));
  await interaction.reply({
    content: `${formatHandLines(player)}\n\n낼 카드의 숫자를 선택하세요. (초록색 = 지금 낼 수 있는 카드)`,
    components: [new ActionRowBuilder().addComponents(select)],
    flags: MessageFlags.Ephemeral,
  });
}

async function openFollowSelect(interaction, game) {
  const player = game.pending.player;
  const { reqRank, reqCount } = game.pending.data;
  const plays = player.getValidPlays(reqCount, reqRank);
  if (plays.length === 0) {
    await interaction.reply({
      content: `${formatHandLines(player, new Set())}\n\n낼 수 있는 카드가 없습니다. **패스** 버튼을 눌러주세요.`,
      flags: MessageFlags.Ephemeral,
    });
    return;
  }
  game.pending.validPlays = plays;
  const validRanks = new Set(plays.map((p) => p.rank));
  const options = plays.map((p, i) => ({
    label: `[${p.rank}] × ${p.count}장${p.jokerCount > 0 ? ` (조커 ${p.jokerCount})` : ""}`,
    value: String(i),
  }));
  const select = new StringSelectMenuBuilder()
    .setCustomId("sel_follow")
    .setPlaceholder("낼 카드를 선택하세요")
    .addOptions(options.slice(0, 25));
  await interaction.reply({
    content: `${formatHandLines(player, validRanks)}\n\n[${reqRank}]보다 낮은 숫자로 ${reqCount}장을 내세요. (초록색 = 지금 낼 수 있는 카드)`,
    components: [new ActionRowBuilder().addComponents(select)],
    flags: MessageFlags.Ephemeral,
  });
}

async function openGiveSelect(interaction, game) {
  const player = game.pending.player;
  const { count, receiverName, allowedIndices } = game.pending.data;
  const sourceIndices =
    allowedIndices && allowedIndices.length > 0 ? allowedIndices : player.hand.map((_, i) => i);
  const options = sourceIndices.map((i) => ({
    label: player.hand[i] === 13 ? "★ 조커" : `[${player.hand[i]}]`,
    value: String(i),
  }));
  const select = new StringSelectMenuBuilder()
    .setCustomId("sel_give")
    .setPlaceholder(`${receiverName}에게 줄 카드 ${count}장을 선택하세요`)
    .setMinValues(count)
    .setMaxValues(count)
    .addOptions(options);
  const restrictNote = allowedIndices ? " (원래 갖고 있던 카드 중에서 골라주세요 - 방금 받은 카드는 제외)" : "";
  await interaction.reply({
    content: `${formatHandLines(player)}\n\n${receiverName}에게 줄 카드 ${count}장을 선택하세요.${restrictNote}`,
    components: [new ActionRowBuilder().addComponents(select)],
    flags: MessageFlags.Ephemeral,
  });
}

// ════════════════════════════════════════
// 게임 진행 (라운드/트릭/카드교환) - dalmuti.js의 규칙 로직을 재사용
// ════════════════════════════════════════

function dealCards(game) {
  const deck = shuffle(createDeck(game.maxRank || 12));
  for (const p of game.players) {
    p.hand = [];
    p.finished = false;
    p.finishOrder = -1;
  }
  game.finishedPlayers = [];
  for (let i = 0; i < deck.length; i++) {
    game.players[i % game.players.length].hand.push(deck[i]);
  }
  for (const p of game.players) p.sortHand();
}

function nextActive(game, idx) {
  const n = game.players.length;
  let next = (idx + 1) % n;
  let attempts = 0;
  while (game.players[next].finished && attempts < n) {
    next = (next + 1) % n;
    attempts++;
  }
  return next;
}

async function promptLead(game, leaderIdx) {
  const player = game.players[leaderIdx];
  const promise = waitForPlayerAction(game, player, "lead", null, () => {
    let play = AIPlayer.prototype.chooseLead.call(player);
    if (!play) {
      const j = player.counts()[13] || 0;
      play = { rank: 1, count: j, jokerCount: j };
    }
    logEvent(game, `⏰ ${player.name}님이 시간 내에 선택하지 않아 자동으로 진행합니다.`);
    return play;
  });
  await showTurn(game, leaderIdx, null, null, null, "lead");
  return promise;
}

async function promptFollow(game, currentIdx, reqRank, reqCount, trickWinnerName) {
  const player = game.players[currentIdx];
  // 낼 수 있는 카드가 없어도 자동 패스하지 않고, 패스 버튼을 직접 누르게 함
  const promise = waitForPlayerAction(game, player, "follow", { reqRank, reqCount }, () => {
    logEvent(game, `⏰ ${player.name}님이 시간 내에 응답하지 않아 자동 패스합니다.`);
    return null;
  });
  await showTurn(game, currentIdx, reqRank, reqCount, trickWinnerName, "follow");
  return promise;
}

async function playTrick(game, leaderIdx) {
  game.log = []; // 트릭이 바뀔 때마다 로그를 비워서 이전 트릭 내용과 섞이지 않게 함
  const leader = game.players[leaderIdx];
  const n = game.players.length;

  let play;
  if (leader instanceof AIPlayer) {
    await showTurn(game, leaderIdx, null, null, null, null);
    await sleep(1200);
    play = leader.chooseLead();
    if (!play) {
      const j = leader.counts()[13] || 0;
      play = { rank: 1, count: j, jokerCount: j };
    }
  } else {
    play = await promptLead(game, leaderIdx);
  }

  leader.removeCards(play.rank, play.count, play.jokerCount);
  const jokerStr = play.jokerCount > 0 ? ` (조커 ${play.jokerCount}장 포함)` : "";
  logEvent(game, `⭕ ${leader.name}: ${cardBadge(play.rank, ANSI.boldYellow)} × ${play.count}장${jokerStr}`);

  let currentRank = play.rank;
  let currentCount = play.count;
  let trickWinnerIdx = leaderIdx;

  if (!leader.hasCards()) {
    leader.finished = true;
    leader.finishOrder = game.finishedPlayers.length;
    game.finishedPlayers.push(leaderIdx);
    logEvent(game, `🎉 ${leader.name} 완료! → ${getTitle(leader.finishOrder, n)}`);
  }

  const passedPlayers = new Set();
  let currentIdx = nextActive(game, leaderIdx);

  while (true) {
    const activeIndices = [];
    for (let i = 0; i < n; i++) if (!game.players[i].finished) activeIndices.push(i);
    if (activeIndices.length <= 1) break;
    if (currentIdx === trickWinnerIdx && !game.players[trickWinnerIdx].finished) break;
    if (game.players[trickWinnerIdx].finished) {
      const nonWinnerActive = activeIndices.filter((i) => i !== trickWinnerIdx);
      if (nonWinnerActive.every((i) => passedPlayers.has(i))) break;
    }

    const player = game.players[currentIdx];
    let result;
    if (player instanceof AIPlayer) {
      await showTurn(game, currentIdx, currentRank, currentCount, game.players[trickWinnerIdx].name, null);
      await sleep(1200);
      result = player.chooseFollow(currentRank, currentCount);
    } else {
      result = await promptFollow(game, currentIdx, currentRank, currentCount, game.players[trickWinnerIdx].name);
    }

    if (result === null) {
      logEvent(game, `❌ ${player.name}: 패스`);
      passedPlayers.add(currentIdx);
    } else {
      player.removeCards(result.rank, result.count, result.jokerCount);
      const jStr = result.jokerCount > 0 ? ` (조커 ${result.jokerCount}장 포함)` : "";
      logEvent(game, `⭕ ${player.name}: ${cardBadge(result.rank, ANSI.boldYellow)} × ${result.count}장${jStr}`);
      currentRank = result.rank;
      trickWinnerIdx = currentIdx;
      passedPlayers.clear();

      if (!player.hasCards()) {
        player.finished = true;
        player.finishOrder = game.finishedPlayers.length;
        game.finishedPlayers.push(currentIdx);
        logEvent(game, `🎉 ${player.name} 완료! → ${getTitle(player.finishOrder, n)}`);
      }
    }
    currentIdx = nextActive(game, currentIdx);
  }

  const activeLeft = game.players.filter((p) => !p.finished);
  if (activeLeft.length > 1 && !game.players[trickWinnerIdx].finished) {
    logEvent(game, `🏆 ${game.players[trickWinnerIdx].name}님이 트릭 승리!`);
  }
  await postLog(game);

  if (!game.players[trickWinnerIdx].finished) return trickWinnerIdx;
  return nextActive(game, trickWinnerIdx);
}

/**
 * giver가 receiver에게 count장을 줌.
 * allowedIndices가 주어지면 giver.hand의 그 인덱스들 중에서만 골라야 함
 * (카드 교환에서 원래 갖고 있던 카드로만 되돌려주도록 - 방금 받은 카드는 제외 - 제한할 때 사용).
 */
async function giveCards(game, giver, receiver, count, allowedIndices = null) {
  let indices;
  const pickAuto = () => (allowedIndices ? autoPickFromIndices(giver, allowedIndices, count) : autoPickGiveIndices(giver, count));

  if (giver instanceof AIPlayer) {
    indices = pickAuto();
  } else {
    const giverIdx = game.players.indexOf(giver);
    const promise = waitForPlayerAction(game, giver, "give", { count, receiverName: receiver.name, allowedIndices }, () => {
      logEvent(game, `⏰ ${giver.name}님이 시간 내에 선택하지 않아 자동으로 진행합니다.`);
      return pickAuto();
    });
    await showTurn(game, giverIdx, null, null, null, "give");
    indices = await promise;
  }

  const sorted = [...indices].sort((a, b) => b - a);
  const given = [];
  for (const idx of sorted) {
    const card = giver.hand[idx];
    giver.hand.splice(idx, 1);
    receiver.hand.push(card);
    given.push(card);
  }
  recordExchangeInfo(game, giver, { given });
  recordExchangeInfo(game, receiver, { received: given });
  logEvent(game, `${giver.name} → ${receiver.name}: 카드 ${given.length}장 전달 (내용 비공개)`);
}

async function cardExchange(game) {
  const n = game.players.length;
  if (n < 4 || game.rankings.length === 0) return;

  game.exchangeInfo = new Map(); // 이번 라운드 교환 내역만 남도록 초기화

  const greatDalmuti = game.players[game.rankings[0]];
  const dalmuti = game.players[game.rankings[1]];
  const peon = game.players[game.rankings[n - 2]];
  const greatPeon = game.players[game.rankings[n - 1]];

  const jokerCount = greatPeon.hand.filter((c) => c === 13).length;
  if (jokerCount === 2) {
    logEvent(game, `🔥 혁명! ${greatPeon.name}이(가) 조커 2장 보유! 카드 교환이 취소됩니다!`);
    await postLog(game);
    return;
  }

  logEvent(game, `📜 카드 교환 시작`);

  // 대빈민 -> 대달무리: 최고 카드 2장 강제 헌납, 대달무리 -> 대빈민: 원래 갖고 있던 카드 중 골라서 되돌려줌
  // (둘은 서로 독립적 - 대달무리는 방금 받은 헌납 카드가 아니라 자기 원래 손패에서 고름)
  const greatDalmutiOwnIndices = greatDalmuti.hand.map((_, i) => i);
  greatPeon.sortHand();
  const bestCards = [];
  for (const card of [...greatPeon.hand]) {
    if (card !== 13 && bestCards.length < 2) bestCards.push(card);
  }
  while (bestCards.length < 2 && greatPeon.hand.includes(13)) bestCards.push(13);
  for (const card of bestCards) {
    const idx = greatPeon.hand.indexOf(card);
    if (idx !== -1) {
      greatPeon.hand.splice(idx, 1);
      greatDalmuti.hand.push(card);
    }
  }
  recordExchangeInfo(game, greatPeon, { given: bestCards });
  recordExchangeInfo(game, greatDalmuti, { received: bestCards });
  logEvent(game, `${greatPeon.name}(대빈민) → ${greatDalmuti.name}(대달무리): 최고 카드 2장 헌납 (내용 비공개)`);

  await giveCards(game, greatDalmuti, greatPeon, 2, greatDalmutiOwnIndices);

  // 빈민 -> 달무리: 최고 카드 1장, 달무리 -> 빈민: 원래 갖고 있던 카드 중 골라서 되돌려줌
  const dalmutiOwnIndices = dalmuti.hand.map((_, i) => i);
  peon.sortHand();
  let bestCard = peon.hand.find((c) => c !== 13);
  if (bestCard === undefined && peon.hand.length > 0) bestCard = peon.hand[0];
  if (bestCard !== undefined) {
    const idx = peon.hand.indexOf(bestCard);
    peon.hand.splice(idx, 1);
    dalmuti.hand.push(bestCard);
    recordExchangeInfo(game, peon, { given: [bestCard] });
    recordExchangeInfo(game, dalmuti, { received: [bestCard] });
    logEvent(game, `${peon.name}(빈민) → ${dalmuti.name}(달무리): 최고 카드 1장 헌납 (내용 비공개)`);
  }

  await giveCards(game, dalmuti, peon, 1, dalmutiOwnIndices);

  for (const p of game.players) p.sortHand();
  await postLog(game);
}

async function showRoundResults(game) {
  const n = game.players.length;
  const lines = [];
  for (let pos = 0; pos < game.rankings.length; pos++) {
    const pidx = game.rankings[pos];
    const p = game.players[pidx];
    const title = getTitle(pos, n);
    const points = n - pos;
    game.scores[p.name] = (game.scores[p.name] || 0) + points;
    lines.push(`${pos + 1}등 ${title} **${p.name}** (+${points}점)`);
  }
  const scoreLines = Object.entries(game.scores)
    .sort((a, b) => b[1] - a[1])
    .map(([name, score]) => `**${name}**: ${score}점`);

  const embed = new EmbedBuilder()
    .setTitle(`📊 라운드 ${game.roundNum} 결과`)
    .setColor(0xfee75c)
    .addFields(
      { name: "순위", value: lines.join("\n") || "-" },
      { name: "누적 점수", value: scoreLines.join("\n") || "-" }
    );
  await game.channel.send({ embeds: [embed] });
}

async function playRound(game) {
  game.roundNum++;
  game.log = [];
  dealCards(game);

  if (game.roundNum > 1 && game.rankings.length > 0) {
    await cardExchange(game);
  }

  let leaderIdx;
  if (game.roundNum === 1) {
    leaderIdx = game.players.findIndex((p) => p.hand.includes(1));
    if (leaderIdx === -1) leaderIdx = 0;
  } else {
    leaderIdx = game.rankings[0];
  }

  game.finishedPlayers = [];

  logEvent(game, `🎬 라운드 ${game.roundNum} 시작!`);
  if (game.roundNum === 1) {
    logEvent(game, `${game.players[leaderIdx].name}이(가) [1] 달무리 카드를 갖고 있어 선으로 시작!`);
  } else {
    logEvent(game, `${game.players[leaderIdx].name}(대달무리)이(가) 선으로 시작!`);
  }
  await postLog(game);
  game.exchangeInfo = null; // "카드 교환 확인" 버튼은 처음에만 뜨면 되므로, 트릭이 시작되면 더는 띄우지 않음

  while (true) {
    const remaining = game.players.map((p, i) => ({ p, i })).filter(({ p }) => !p.finished);
    if (remaining.length <= 1) {
      if (remaining.length === 1) {
        const last = remaining[0];
        last.p.finished = true;
        last.p.finishOrder = game.finishedPlayers.length;
        game.finishedPlayers.push(last.i);
      }
      break;
    }
    while (game.players[leaderIdx].finished) leaderIdx = nextActive(game, leaderIdx);
    leaderIdx = await playTrick(game, leaderIdx);
  }

  game.rankings = [...game.finishedPlayers];
  await showRoundResults(game);
}

async function askContinue(game) {
  const embed = buildPublicEmbed(game, {});
  await postStatus(game, embed, [buildActionRow("continue")]);
  return waitForHostChoice(game);
}

async function finishGame(game) {
  const sorted = Object.entries(game.scores).sort((a, b) => b[1] - a[1]);
  const medals = ["🥇", "🥈", "🥉"];
  const lines = sorted.map(([name, score], i) => `${medals[i] || "　"} **${name}**: ${score}점`);
  const embed = new EmbedBuilder()
    .setTitle("🏆 최종 결과")
    .setColor(0xeb459e)
    .setDescription(lines.join("\n") || "-")
    .setFooter({ text: "게임을 플레이해주셔서 감사합니다! 🎴" });
  await game.channel.send({ embeds: [embed] });
}

async function runGame(game) {
  const humanCount = game.players.filter((p) => !(p instanceof AIPlayer)).length;
  const aiCount = game.players.length - humanCount;
  logEvent(game, `게임을 시작합니다! (사람 ${humanCount}명 + AI ${aiCount}명)`);
  await postLog(game);

  while (true) {
    await playRound(game);
    const cont = await askContinue(game);
    if (!cont) break;
  }

  await finishGame(game);
  games.delete(game.channel.id);
}

// ════════════════════════════════════════
// 스플렌더 - 로비(참가자 모집)
// ════════════════════════════════════════

function buildSplendorLobbyEmbed(lobby) {
  const names = [...lobby.players.values()].map((p) => `🙂 ${p.username}`).join("\n") || "-";
  const aiCount = Math.max(0, lobby.total - lobby.players.size);
  return new EmbedBuilder()
    .setTitle("💎 스플렌더 - 참가자 모집")
    .setColor(0x9b59b6)
    .setDescription(
      `아래 **참가하기** 버튼을 눌러 참여하세요.\n호스트(<@${lobby.hostId}>)가 **게임 시작**을 누르면 시작합니다.`
    )
    .addFields(
      { name: `참가자 (${lobby.players.size}명)`, value: names },
      {
        name: "총 인원",
        value: `${lobby.total}명 (사람 ${lobby.players.size}명 + 부족한 자리는 AI ${aiCount}명이 채웁니다, 최대 4명)`,
      }
    );
}

function buildSplendorLobbyComponents(lobby) {
  const totalSelect = new StringSelectMenuBuilder()
    .setCustomId("sp_lobby_total")
    .setPlaceholder(`총 인원: ${lobby.total}명 (호스트만 변경 가능)`)
    .addOptions([2, 3, 4].map((n) => ({ label: `${n}명`, value: String(n), default: n === lobby.total })));
  const row1 = new ActionRowBuilder().addComponents(totalSelect);
  const row2 = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId("sp_lobby_join").setLabel("참가하기").setStyle(ButtonStyle.Success),
    new ButtonBuilder().setCustomId("sp_lobby_leave").setLabel("나가기").setStyle(ButtonStyle.Secondary),
    new ButtonBuilder().setCustomId("sp_lobby_start").setLabel("게임 시작").setStyle(ButtonStyle.Primary)
  );
  return [row1, row2];
}

async function refreshSplendorLobby(interaction, lobby) {
  await interaction.update({ embeds: [buildSplendorLobbyEmbed(lobby)], components: buildSplendorLobbyComponents(lobby) });
}

async function splLobbyJoin(interaction) {
  const lobby = splendorLobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (lobby.players.size >= 4) {
    return interaction.reply({ content: "최대 4명까지 참가할 수 있습니다.", flags: MessageFlags.Ephemeral });
  }
  lobby.players.set(interaction.user.id, { id: interaction.user.id, username: interaction.user.username });
  if (lobby.players.size > lobby.total) lobby.total = lobby.players.size;
  await refreshSplendorLobby(interaction, lobby);
}

async function splLobbyLeave(interaction) {
  const lobby = splendorLobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (interaction.user.id === lobby.hostId) {
    return interaction.reply({
      content: "호스트는 나갈 수 없습니다. 모집을 취소하려면 관리자에게 메시지 삭제를 요청하세요.",
      flags: MessageFlags.Ephemeral,
    });
  }
  lobby.players.delete(interaction.user.id);
  await refreshSplendorLobby(interaction, lobby);
}

async function splLobbySetTotal(interaction) {
  const lobby = splendorLobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (interaction.user.id !== lobby.hostId) {
    return interaction.reply({ content: "호스트만 인원 수를 바꿀 수 있습니다.", flags: MessageFlags.Ephemeral });
  }
  const val = parseInt(interaction.values[0]);
  lobby.total = Math.max(val, lobby.players.size, 2);
  await refreshSplendorLobby(interaction, lobby);
}

async function splLobbyStart(interaction) {
  const lobby = splendorLobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (interaction.user.id !== lobby.hostId) {
    return interaction.reply({ content: "호스트만 게임을 시작할 수 있습니다.", flags: MessageFlags.Ephemeral });
  }

  splendorLobbies.delete(interaction.channelId);
  await interaction.update({ embeds: [buildSplendorLobbyEmbed(lobby)], components: [] });

  const playersInput = [];
  for (const p of lobby.players.values()) {
    playersInput.push({ id: p.id, name: p.username, isAI: false, discordId: p.id });
  }
  const aiCount = Math.max(0, lobby.total - playersInput.length);
  for (let i = 0; i < aiCount; i++) playersInput.push({ id: `ai-${i}`, name: `AI-${i + 1}`, isAI: true });
  shuffle(playersInput); // 사람이 항상 먼저 나오지 않도록 순서(자리)를 섞음

  const game = Spl.newGame(playersInput);
  game.channel = lobby.channel;
  game.hostId = lobby.hostId;
  game.statusMessage = null;
  splendorGames.set(interaction.channelId, game);

  runSplendorGame(game).catch((err) => {
    console.error(err);
    game.channel.send("⚠️ 게임 중 오류가 발생하여 게임을 종료합니다.").catch(() => {});
    splendorGames.delete(interaction.channelId);
  });
}

// ════════════════════════════════════════
// 스플렌더 - 화면(상태 메시지) 렌더링
// ════════════════════════════════════════

const SLOT_LETTERS = ["A", "B", "C", "D"];

function splCostText(cost) {
  const parts = Spl.COLORS.filter((c) => cost[c] > 0).map((c) => `${Spl.GEM_INFO[c].emoji}${cost[c]}`);
  return parts.length ? parts.join(" ") : "무료";
}

function splTierBlock(game, tier) {
  const lines = game.board[tier].map((card, i) => {
    if (!card) return `${ANSI.dim}[T${tier}${SLOT_LETTERS[i]}] (없음)${ANSI.reset}`;
    const bonus = Spl.GEM_INFO[card.color].emoji;
    const pts = card.points > 0 ? ` 🏆${card.points}` : "";
    return `[T${tier}${SLOT_LETTERS[i]}] ${bonus}${pts}  ${splCostText(card.cost)}`;
  });
  lines.push(`${ANSI.dim}(덱 ${game.decks[tier].length}장 남음)${ANSI.reset}`);
  return lines.join("\n");
}

function splNoblesBlock(game) {
  if (game.nobles.length === 0) return `${ANSI.dim}없음${ANSI.reset}`;
  return game.nobles.map((n, i) => `N${i + 1}: ${splCostText(n.cost)}  🏆${n.points}`).join("\n");
}

function splBankBlock(game) {
  const parts = Spl.COLORS.map((c) => `${Spl.GEM_INFO[c].emoji}${game.tokens[c]}`);
  parts.push(`${Spl.GEM_INFO.gold.emoji}${game.tokens.gold}`);
  return parts.join(" ");
}

function splPlayersBlock(game, currentIdx) {
  return game.players
    .map((p, i) => {
      const tag = p.isAI ? "🤖" : "🙂";
      const bonuses = Spl.COLORS.map((c) => `${Spl.GEM_INFO[c].emoji}${p.bonuses[c]}`).join(" ");
      const tokenTotal = Spl.tokenTotal(p.tokens);
      const line = `${tag} ${p.name} — 🏆${p.points}점 | 토큰 ${tokenTotal}개 | 예약 ${p.reserved.length}장\n   보너스: ${bonuses}`;
      if (i === currentIdx) return `${ANSI.boldGreen}▶ ${line}${ANSI.reset}`;
      return line;
    })
    .join("\n");
}

function buildSplendorBoardEmbed(game, opts = {}) {
  const embed = new EmbedBuilder()
    .setTitle(`💎 스플렌더 - ${game.turnNumber}턴째`)
    .setColor(0x9b59b6)
    .addFields(
      { name: "👑 귀족", value: ansiBlock(splNoblesBlock(game)) },
      { name: "🃏 티어 3", value: ansiBlock(splTierBlock(game, 3)) },
      { name: "🃏 티어 2", value: ansiBlock(splTierBlock(game, 2)) },
      { name: "🃏 티어 1", value: ansiBlock(splTierBlock(game, 1)) },
      { name: "🏦 토큰 은행", value: ansiBlock(splBankBlock(game)) },
      { name: "플레이어", value: ansiBlock(splPlayersBlock(game, opts.currentIdx)) }
    );

  if (game.pending) {
    if (game.pending.kind === "discard") {
      embed.addFields({
        name: "⚠️ 안내",
        value: `보유 토큰이 10개를 초과했습니다. ${game.pending.data.overflow}개를 반납해야 합니다.`,
      });
    } else if (game.pending.kind === "noble") {
      embed.addFields({ name: "👑 안내", value: "방문 가능한 귀족이 여러 명입니다. 한 명을 선택하세요." });
    }
  }

  if (game.log.length > 0) {
    embed.addFields({ name: "진행 로그", value: ansiBlock(game.log.slice(-8).join("\n").slice(0, 1000)) });
  }

  if (game.pending && game.pending.deadline) {
    const sec = Math.round(game.pending.deadline / 1000);
    embed.addFields({
      name: "⏰ 제한시간",
      value: `<t:${sec}:R> 까지 응답이 없으면 자동으로 진행됩니다.`,
    });
  }
  return embed;
}

function buildSplendorActionRow(kind) {
  if (!kind) return null;
  const row = new ActionRowBuilder();
  if (kind === "action") {
    row.addComponents(
      new ButtonBuilder().setCustomId("sp_act_tokens").setLabel("토큰 가져오기").setStyle(ButtonStyle.Primary),
      new ButtonBuilder().setCustomId("sp_act_buy").setLabel("카드 구매").setStyle(ButtonStyle.Success),
      new ButtonBuilder().setCustomId("sp_act_reserve").setLabel("카드 예약").setStyle(ButtonStyle.Secondary)
    );
    return row;
  }
  if (kind === "discard") {
    row.addComponents(new ButtonBuilder().setCustomId("sp_act_discard").setLabel("토큰 반납하기").setStyle(ButtonStyle.Danger));
    return row;
  }
  if (kind === "noble") {
    row.addComponents(new ButtonBuilder().setCustomId("sp_act_noble").setLabel("귀족 선택하기").setStyle(ButtonStyle.Primary));
    return row;
  }
  return null;
}

async function postSplendorStatus(game, embed, rows) {
  const payload = { embeds: [embed], components: rows };
  const prevMessage = game.statusMessage;
  game.statusMessage = await game.channel.send(payload);
  if (prevMessage) {
    prevMessage.edit({ components: [] }).catch(() => {});
  }
}

async function showSplendorTurn(game, currentIdx, kind) {
  const embed = buildSplendorBoardEmbed(game, { currentIdx });
  const rows = [buildSplendorActionRow(kind)].filter(Boolean);
  await postSplendorStatus(game, embed, rows);
}

async function postSplendorLog(game) {
  await postSplendorStatus(game, buildSplendorBoardEmbed(game, {}), []);
}

// ════════════════════════════════════════
// 스플렌더 - 사람 입력을 여는 select 메뉴들
// ════════════════════════════════════════

function splDiscardUnits(player) {
  const units = [];
  for (const c of [...Spl.COLORS, "gold"]) {
    for (let i = 0; i < player.tokens[c]; i++) units.push(c);
  }
  return units;
}

async function openSplTokensSelect(interaction, game) {
  const take3Colors = Spl.COLORS.filter((c) => game.tokens[c] >= 1);
  const take2Colors = Spl.COLORS.filter((c) => game.tokens[c] >= 4);

  if (take3Colors.length === 0 && take2Colors.length === 0) {
    return interaction.reply({
      content: "은행에 가져올 수 있는 토큰이 없습니다. 카드 구매나 예약을 시도해보세요.",
      flags: MessageFlags.Ephemeral,
    });
  }

  const rows = [];
  if (take3Colors.length > 0) {
    const select = new StringSelectMenuBuilder()
      .setCustomId("sp_sel_take3")
      .setPlaceholder("서로 다른 색 토큰 최대 3개 선택")
      .setMinValues(1)
      .setMaxValues(Math.min(3, take3Colors.length))
      .addOptions(take3Colors.map((c) => ({ label: Spl.GEM_INFO[c].label, value: c, emoji: Spl.GEM_INFO[c].emoji })));
    rows.push(new ActionRowBuilder().addComponents(select));
  }
  if (take2Colors.length > 0) {
    const select = new StringSelectMenuBuilder()
      .setCustomId("sp_sel_take2")
      .setPlaceholder("같은 색 토큰 2개 선택 (은행에 4개 이상 있는 색만 가능)")
      .addOptions(take2Colors.map((c) => ({ label: Spl.GEM_INFO[c].label, value: c, emoji: Spl.GEM_INFO[c].emoji })));
    rows.push(new ActionRowBuilder().addComponents(select));
  }

  await interaction.reply({
    content: "가져올 토큰을 선택하세요. (서로 다른 색 최대 3개 **또는** 같은 색 2개 중 하나만 선택)",
    components: rows,
    flags: MessageFlags.Ephemeral,
  });
}

async function openSplBuySelect(interaction, game) {
  const player = game.pending.player;
  const options = [];
  Spl.allBoardCards(game).forEach(({ card, tier, slotIdx }) => {
    const afford = Spl.canAfford(card, player) ? "✅" : "❌";
    options.push({
      label: `${afford} [T${tier}${SLOT_LETTERS[slotIdx]}] ${Spl.GEM_INFO[card.color].emoji} 보너스${card.points > 0 ? ` 🏆${card.points}` : ""}`,
      description: `비용: ${splCostText(card.cost)}`.slice(0, 100),
      value: `board:${tier}:${slotIdx}`,
    });
  });
  player.reserved.forEach((card, i) => {
    const afford = Spl.canAfford(card, player) ? "✅" : "❌";
    options.push({
      label: `${afford} [예약${i + 1}] ${Spl.GEM_INFO[card.color].emoji} 보너스${card.points > 0 ? ` 🏆${card.points}` : ""}`,
      description: `비용: ${splCostText(card.cost)}`.slice(0, 100),
      value: `reserved:${i}`,
    });
  });

  if (options.length === 0) {
    return interaction.reply({ content: "구매할 수 있는 카드가 없습니다.", flags: MessageFlags.Ephemeral });
  }

  const select = new StringSelectMenuBuilder()
    .setCustomId("sp_sel_buy")
    .setPlaceholder("구매할 카드를 선택하세요 (✅ = 구매 가능)")
    .addOptions(options.slice(0, 25));
  await interaction.reply({
    content: `${formatSplHand(player)}\n\n구매할 카드를 선택하세요.`,
    components: [new ActionRowBuilder().addComponents(select)],
    flags: MessageFlags.Ephemeral,
  });
}

async function openSplReserveSelect(interaction, game) {
  const player = game.pending.player;
  if (player.reserved.length >= Spl.MAX_RESERVED) {
    return interaction.reply({ content: "이미 예약 카드가 3장입니다. 예약할 수 없습니다.", flags: MessageFlags.Ephemeral });
  }

  const options = [];
  Spl.allBoardCards(game).forEach(({ card, tier, slotIdx }) => {
    options.push({
      label: `[T${tier}${SLOT_LETTERS[slotIdx]}] ${Spl.GEM_INFO[card.color].emoji} 보너스${card.points > 0 ? ` 🏆${card.points}` : ""}`,
      description: `비용: ${splCostText(card.cost)}`.slice(0, 100),
      value: `board:${tier}:${slotIdx}`,
    });
  });
  for (const tier of [1, 2, 3]) {
    if (game.decks[tier].length > 0) {
      options.push({
        label: `[T${tier} 덱] 맨 위 카드 비공개로 예약`,
        description: `해당 티어 덱에 ${game.decks[tier].length}장 남음`,
        value: `blind:${tier}`,
      });
    }
  }

  if (options.length === 0) {
    return interaction.reply({ content: "예약할 수 있는 카드가 없습니다.", flags: MessageFlags.Ephemeral });
  }

  const select = new StringSelectMenuBuilder()
    .setCustomId("sp_sel_reserve")
    .setPlaceholder("예약할 카드를 선택하세요")
    .addOptions(options.slice(0, 25));
  await interaction.reply({
    content: `예약할 카드를 선택하세요. (은행에 금 토큰이 있으면 1개를 함께 받습니다)`,
    components: [new ActionRowBuilder().addComponents(select)],
    flags: MessageFlags.Ephemeral,
  });
}

async function openSplDiscardSelect(interaction, game) {
  const player = game.pending.player;
  const overflow = game.pending.data.overflow;
  const units = splDiscardUnits(player);
  const options = units.map((c, i) => ({
    label: `${Spl.GEM_INFO[c].label}`,
    value: String(i),
    emoji: Spl.GEM_INFO[c].emoji,
  }));
  const select = new StringSelectMenuBuilder()
    .setCustomId("sp_sel_discard")
    .setPlaceholder(`반납할 토큰 ${overflow}개를 선택하세요`)
    .setMinValues(overflow)
    .setMaxValues(overflow)
    .addOptions(options.slice(0, 25));
  await interaction.reply({
    content: `토큰을 ${overflow}개 반납해야 합니다 (10개 초과 보유).`,
    components: [new ActionRowBuilder().addComponents(select)],
    flags: MessageFlags.Ephemeral,
  });
}

async function openSplNobleSelect(interaction, game) {
  const eligible = game.pending.data.eligible;
  const options = eligible.map((idx) => {
    const noble = game.nobles[idx];
    return { label: `N${idx + 1}: ${splCostText(noble.cost)} (🏆${noble.points})`, value: String(idx) };
  });
  const select = new StringSelectMenuBuilder()
    .setCustomId("sp_sel_noble")
    .setPlaceholder("방문할 귀족을 선택하세요")
    .addOptions(options);
  await interaction.reply({
    content: "방문 가능한 귀족이 여러 명입니다. 한 명을 선택하세요.",
    components: [new ActionRowBuilder().addComponents(select)],
    flags: MessageFlags.Ephemeral,
  });
}

function formatSplHand(player) {
  const tokens = Spl.COLORS.map((c) => `${Spl.GEM_INFO[c].emoji}${player.tokens[c]}`).join(" ") + ` ${Spl.GEM_INFO.gold.emoji}${player.tokens.gold}`;
  const bonuses = Spl.COLORS.map((c) => `${Spl.GEM_INFO[c].emoji}${player.bonuses[c]}`).join(" ");
  return `**내 토큰**\n${ansiBlock(tokens)}\n**내 보너스**\n${ansiBlock(bonuses)}`;
}

// ════════════════════════════════════════
// 스플렌더 - 게임 진행
// ════════════════════════════════════════

function applySplendorAction(game, idx, action) {
  switch (action.type) {
    case "take3":
      return Spl.doTake3(game, idx, action.colors);
    case "take2":
      return Spl.doTake2(game, idx, action.color);
    case "buyBoard":
      return Spl.doBuyBoard(game, idx, action.tier, action.slotIdx);
    case "buyReserved":
      return Spl.doBuyReserved(game, idx, action.reservedIdx);
    case "reserveBoard":
      return Spl.doReserveBoard(game, idx, action.tier, action.slotIdx);
    case "reserveBlind":
      return Spl.doReserveBlind(game, idx, action.tier);
    case "pass":
      return { ok: true };
    default:
      return { ok: false, error: "알 수 없는 행동입니다." };
  }
}

async function promptSplendorAction(game, idx) {
  const player = game.players[idx];
  const promise = waitForPlayerAction(
    game,
    player,
    "action",
    null,
    () => {
      Spl.logEvent(game, `⏰ ${player.name}님이 시간 내에 선택하지 않아 자동으로 진행합니다.`);
      return Spl.chooseAIAction(game, idx);
    },
    SPLENDOR_TURN_TIMEOUT_MS
  );
  await showSplendorTurn(game, idx, "action");
  return promise;
}

async function promptSplendorDiscard(game, idx, overflow) {
  const player = game.players[idx];
  const promise = waitForPlayerAction(
    game,
    player,
    "discard",
    { overflow },
    () => {
      Spl.logEvent(game, `⏰ ${player.name}님이 시간 내에 반납하지 않아 자동으로 반납합니다.`);
      return Spl.autoDiscardPlan(player);
    },
    SPLENDOR_TURN_TIMEOUT_MS
  );
  await showSplendorTurn(game, idx, "discard");
  return promise;
}

async function promptSplendorNoble(game, idx, eligible) {
  const player = game.players[idx];
  const promise = waitForPlayerAction(
    game,
    player,
    "noble",
    { eligible },
    () => {
      Spl.logEvent(game, `⏰ ${player.name}님이 시간 내에 선택하지 않아 자동으로 선택합니다.`);
      return Spl.chooseAINoble(game, idx, eligible);
    },
    SPLENDOR_TURN_TIMEOUT_MS
  );
  await showSplendorTurn(game, idx, "noble");
  return promise;
}

async function playSplendorTurn(game, idx) {
  const player = game.players[idx];
  let action;
  if (player.isAI) {
    await showSplendorTurn(game, idx, null);
    await sleep(1200);
    action = Spl.chooseAIAction(game, idx);
  } else {
    action = await promptSplendorAction(game, idx);
  }

  const result = applySplendorAction(game, idx, action);
  if (!result.ok) {
    Spl.logEvent(game, `⚠️ ${player.name}: 행동을 처리할 수 없어 이번 턴을 넘깁니다. (${result.error})`);
  }

  const overflow = Spl.overflowCount(player);
  if (overflow > 0) {
    let plan;
    if (player.isAI) {
      plan = Spl.autoDiscardPlan(player);
    } else {
      plan = await promptSplendorDiscard(game, idx, overflow);
    }
    Spl.discardTokens(game, idx, plan);
  }

  let eligible = Spl.getEligibleNobles(game, idx);
  while (eligible.length > 0) {
    let nobleIdx;
    if (player.isAI || eligible.length === 1) {
      nobleIdx = Spl.chooseAINoble(game, idx, eligible);
    } else {
      nobleIdx = await promptSplendorNoble(game, idx, eligible);
    }
    Spl.claimNoble(game, idx, nobleIdx);
    eligible = Spl.getEligibleNobles(game, idx);
  }

  await postSplendorLog(game);
  return Spl.noteTurnEnded(game, idx);
}

async function finishSplendorGame(game) {
  const winners = Spl.getWinners(game);
  const winnerIds = new Set(winners.map((w) => w.id));
  const sorted = [...game.players].sort((a, b) => b.points - a.points || a.cards.length - b.cards.length);
  const medals = ["🥇", "🥈", "🥉"];
  const lines = sorted.map((p, i) => {
    const crown = winnerIds.has(p.id) ? " 👑" : "";
    return `${medals[i] || "　"} **${p.name}**${crown}: 🏆${p.points}점 (카드 ${p.cards.length}장, 귀족 ${p.nobles.length}명)`;
  });
  const embed = new EmbedBuilder()
    .setTitle("🏆 게임 종료!")
    .setColor(0xeb459e)
    .setDescription(`**우승자: ${winners.map((w) => w.name).join(", ")}** 🎉\n\n` + lines.join("\n"))
    .setFooter({ text: "스플렌더를 플레이해주셔서 감사합니다! 💎" });
  await game.channel.send({ embeds: [embed] });
}

async function runSplendorGame(game) {
  const humanCount = game.players.filter((p) => !p.isAI).length;
  const aiCount = game.players.length - humanCount;
  Spl.logEvent(game, `게임을 시작합니다! (사람 ${humanCount}명 + AI ${aiCount}명, 목표 ${Spl.WIN_POINTS}점)`);
  await postSplendorLog(game);

  while (true) {
    const idx = game.currentIdx;
    const ended = await playSplendorTurn(game, idx);
    if (ended) break;
    game.currentIdx = Spl.nextIdx(game, idx);
    game.turnNumber++;
  }

  await finishSplendorGame(game);
  splendorGames.delete(game.channel.id);
}

// ════════════════════════════════════════
// 스플렌더 - 인터랙션 라우팅
// ════════════════════════════════════════

async function handleSplendorButton(interaction) {
  const { customId } = interaction;

  if (customId === "sp_lobby_join") return splLobbyJoin(interaction);
  if (customId === "sp_lobby_leave") return splLobbyLeave(interaction);
  if (customId === "sp_lobby_start") return splLobbyStart(interaction);

  const ACTION_KINDS = {
    sp_act_tokens: "action",
    sp_act_buy: "action",
    sp_act_reserve: "action",
    sp_act_discard: "discard",
    sp_act_noble: "noble",
  };
  if (customId in ACTION_KINDS) {
    const game = splendorGames.get(interaction.channelId);
    if (!game || !game.pending) {
      return interaction.reply({ content: "지금은 진행 중인 턴이 없습니다.", flags: MessageFlags.Ephemeral });
    }
    if (game.pending.playerId !== interaction.user.id) {
      return interaction.reply({ content: "당신의 차례가 아닙니다.", flags: MessageFlags.Ephemeral });
    }
    if (game.pending.kind !== ACTION_KINDS[customId]) {
      return interaction.reply({ content: "지금은 할 수 없는 행동입니다.", flags: MessageFlags.Ephemeral });
    }
    if (customId === "sp_act_tokens") return openSplTokensSelect(interaction, game);
    if (customId === "sp_act_buy") return openSplBuySelect(interaction, game);
    if (customId === "sp_act_reserve") return openSplReserveSelect(interaction, game);
    if (customId === "sp_act_discard") return openSplDiscardSelect(interaction, game);
    if (customId === "sp_act_noble") return openSplNobleSelect(interaction, game);
  }
}

async function handleSplendorSelect(interaction) {
  if (interaction.customId === "sp_lobby_total") return splLobbySetTotal(interaction);

  const game = splendorGames.get(interaction.channelId);
  if (!game || !game.pending || game.pending.playerId !== interaction.user.id) {
    return interaction.update({ content: "이 선택은 더 이상 유효하지 않습니다.", components: [] }).catch(() => {});
  }

  if (interaction.customId === "sp_sel_take3") {
    const colors = interaction.values;
    await interaction.update({
      content: `✅ 토큰 ${colors.map((c) => Spl.GEM_INFO[c].emoji).join(" ")} 획득`,
      components: [],
    });
    game.pending.resolve({ type: "take3", colors });
    return;
  }

  if (interaction.customId === "sp_sel_take2") {
    const color = interaction.values[0];
    await interaction.update({
      content: `✅ 토큰 ${Spl.GEM_INFO[color].emoji}${Spl.GEM_INFO[color].emoji} 획득`,
      components: [],
    });
    game.pending.resolve({ type: "take2", color });
    return;
  }

  if (interaction.customId === "sp_sel_buy") {
    const parts = interaction.values[0].split(":");
    const player = game.pending.player;
    let card;
    if (parts[0] === "board") card = game.board[Number(parts[1])][Number(parts[2])];
    else card = player.reserved[Number(parts[1])];

    if (!card || !Spl.canAfford(card, player)) {
      return interaction.reply({
        content: "구매할 수 없습니다 (토큰이 부족하거나 자리가 바뀌었습니다). 다시 선택해주세요.",
        flags: MessageFlags.Ephemeral,
      });
    }
    await interaction.update({ content: `✅ 카드를 구매합니다.`, components: [] });
    if (parts[0] === "board") game.pending.resolve({ type: "buyBoard", tier: Number(parts[1]), slotIdx: Number(parts[2]) });
    else game.pending.resolve({ type: "buyReserved", reservedIdx: Number(parts[1]) });
    return;
  }

  if (interaction.customId === "sp_sel_reserve") {
    const parts = interaction.values[0].split(":");
    if (game.pending.player.reserved.length >= Spl.MAX_RESERVED) {
      return interaction.reply({ content: "이미 예약 카드가 3장입니다.", flags: MessageFlags.Ephemeral });
    }
    await interaction.update({ content: `✅ 카드를 예약합니다.`, components: [] });
    if (parts[0] === "board") game.pending.resolve({ type: "reserveBoard", tier: Number(parts[1]), slotIdx: Number(parts[2]) });
    else game.pending.resolve({ type: "reserveBlind", tier: Number(parts[1]) });
    return;
  }

  if (interaction.customId === "sp_sel_discard") {
    const indices = interaction.values.map(Number);
    const units = splDiscardUnits(game.pending.player);
    const colorCounts = {};
    for (const idx of indices) {
      const c = units[idx];
      colorCounts[c] = (colorCounts[c] || 0) + 1;
    }
    await interaction.update({ content: `✅ 토큰을 반납합니다.`, components: [] });
    game.pending.resolve(colorCounts);
    return;
  }

  if (interaction.customId === "sp_sel_noble") {
    const idx = Number(interaction.values[0]);
    await interaction.update({ content: `✅ 귀족을 선택합니다.`, components: [] });
    game.pending.resolve(idx);
    return;
  }
}

async function handleSplendorSlashCommand(interaction) {
  const channelId = interaction.channelId;
  if (splendorGames.has(channelId) || games.has(channelId)) {
    return interaction.reply({ content: "이미 이 채널에서 게임이 진행 중입니다.", flags: MessageFlags.Ephemeral });
  }
  if (splendorLobbies.has(channelId) || lobbies.has(channelId)) {
    return interaction.reply({
      content: "이미 모집 중인 게임이 있습니다. 아래 메시지에서 참가해주세요.",
      flags: MessageFlags.Ephemeral,
    });
  }
  const lobby = {
    hostId: interaction.user.id,
    channel: interaction.channel,
    players: new Map([[interaction.user.id, { id: interaction.user.id, username: interaction.user.username }]]),
    total: 4,
  };
  splendorLobbies.set(channelId, lobby);
  await interaction.reply({ embeds: [buildSplendorLobbyEmbed(lobby)], components: buildSplendorLobbyComponents(lobby) });
}

// ════════════════════════════════════════
// 인터랙션 라우팅
// ════════════════════════════════════════

async function handleButton(interaction) {
  const { customId } = interaction;

  if (customId.startsWith("sp_")) return handleSplendorButton(interaction);

  if (customId === "lobby_join") return lobbyJoin(interaction);
  if (customId === "lobby_leave") return lobbyLeave(interaction);
  if (customId === "lobby_start") return lobbyStart(interaction);

  if (customId === "check_exchange") {
    const game = games.get(interaction.channelId);
    const info = game && game.exchangeInfo && game.exchangeInfo.get(interaction.user.id);
    if (!info || (info.given.length === 0 && info.received.length === 0)) {
      return interaction.reply({
        content: "이번 카드 교환에서 오간 카드가 없습니다.",
        flags: MessageFlags.Ephemeral,
      });
    }
    const parts = [];
    if (info.received.length > 0) {
      const badges = info.received.map((c) => cardBadge(c, ANSI.boldGreen)).join(" ");
      parts.push(`받은 카드 (${info.received.length}장):\n${ansiBlock(badges)}`);
    }
    if (info.given.length > 0) {
      const badges = info.given.map((c) => cardBadge(c, ANSI.dim)).join(" ");
      parts.push(`낸 카드 (${info.given.length}장):\n${ansiBlock(badges)}`);
    }
    return interaction.reply({
      content: `🎴 이번 카드 교환 내역 (다른 사람에게는 비공개)\n` + parts.join("\n"),
      flags: MessageFlags.Ephemeral,
    });
  }

  if (customId === "cont_yes" || customId === "cont_no") {
    const game = games.get(interaction.channelId);
    if (!game || !game.pending || game.pending.kind !== "continue") {
      return interaction.reply({ content: "지금은 응답할 시점이 아닙니다.", flags: MessageFlags.Ephemeral });
    }
    if (interaction.user.id !== game.pending.playerId) {
      return interaction.reply({ content: "호스트만 선택할 수 있습니다.", flags: MessageFlags.Ephemeral });
    }
    await interaction.reply({
      content: customId === "cont_yes" ? "다음 라운드를 시작합니다." : "게임을 종료합니다.",
      flags: MessageFlags.Ephemeral,
    });
    game.pending.resolve(customId === "cont_yes");
    return;
  }

  if (customId === "act_play" || customId === "act_pass") {
    const game = games.get(interaction.channelId);
    if (!game || !game.pending) {
      return interaction.reply({ content: "지금은 진행 중인 턴이 없습니다.", flags: MessageFlags.Ephemeral });
    }
    if (game.pending.playerId !== interaction.user.id) {
      return interaction.reply({ content: "당신의 차례가 아닙니다.", flags: MessageFlags.Ephemeral });
    }
    const kind = game.pending.kind;
    if (customId === "act_pass") {
      if (kind !== "follow") {
        return interaction.reply({ content: "지금은 패스할 수 없습니다.", flags: MessageFlags.Ephemeral });
      }
      await interaction.reply({ content: "패스했습니다.", flags: MessageFlags.Ephemeral });
      game.pending.resolve(null);
      return;
    }
    if (kind === "lead") return openLeadRankSelect(interaction, game);
    if (kind === "follow") return openFollowSelect(interaction, game);
    if (kind === "give") return openGiveSelect(interaction, game);
    return interaction.reply({ content: "알 수 없는 상태입니다.", flags: MessageFlags.Ephemeral });
  }
}

async function handleSelect(interaction) {
  if (interaction.customId.startsWith("sp_")) return handleSplendorSelect(interaction);

  if (interaction.customId === "lobby_total") return lobbySetTotal(interaction);
  if (interaction.customId === "lobby_maxrank") return lobbySetMaxRank(interaction);

  const game = games.get(interaction.channelId);
  if (!game || !game.pending || game.pending.playerId !== interaction.user.id) {
    return interaction.update({ content: "이 선택은 더 이상 유효하지 않습니다.", components: [] }).catch(() => {});
  }

  if (interaction.customId === "sel_lead_rank") {
    const rank = parseInt(interaction.values[0]);
    const player = game.pending.player;
    const counts = player.counts();
    const available = counts[rank] || 0;
    const jokers = counts[13] || 0;
    const maxCount = available + jokers;

    if (maxCount === 1) {
      // 낼 수 있는 장수가 1장뿐이면 몇 장 낼지 물어볼 필요가 없으므로 바로 냄
      await interaction.update({
        content: `✅ ${ansiBlock(cardBadge(rank, ANSI.boldGreen))} × 1장 냅니다.`,
        components: [],
      });
      game.pending.resolve({ rank, count: 1, jokerCount: 0 });
      return;
    }

    const options = [];
    for (let c = 1; c <= maxCount; c++) {
      const jUsed = Math.max(0, c - available);
      options.push({ label: `${c}장${jUsed > 0 ? ` (조커 ${jUsed}장 포함)` : ""}`, value: String(c) });
    }
    const select = new StringSelectMenuBuilder()
      .setCustomId(`sel_lead_count:${rank}`)
      .setPlaceholder("몇 장을 내시겠습니까?")
      .addOptions(options.slice(0, 25));
    await interaction.update({
      content: ansiBlock(cardBadge(rank, ANSI.boldGreen)) + " 선택됨. 몇 장을 내시겠습니까?",
      components: [new ActionRowBuilder().addComponents(select)],
    });
    return;
  }

  if (interaction.customId.startsWith("sel_lead_count:")) {
    const rank = parseInt(interaction.customId.split(":")[1]);
    const count = parseInt(interaction.values[0]);
    const player = game.pending.player;
    const available = player.counts()[rank] || 0;
    const jokerCount = Math.max(0, count - available);
    await interaction.update({
      content: `✅ ${ansiBlock(cardBadge(rank, ANSI.boldGreen))} × ${count}장 냅니다.`,
      components: [],
    });
    game.pending.resolve({ rank, count, jokerCount });
    return;
  }

  if (interaction.customId === "sel_follow") {
    const idx = parseInt(interaction.values[0]);
    const play = game.pending.validPlays[idx];
    await interaction.update({
      content: `✅ ${ansiBlock(cardBadge(play.rank, ANSI.boldGreen))} × ${play.count}장 냅니다.`,
      components: [],
    });
    game.pending.resolve(play);
    return;
  }

  if (interaction.customId === "sel_give") {
    const indices = interaction.values.map(Number);
    const player = game.pending.player;
    const cards = indices.map((i) => player.hand[i]);
    await interaction.update({ content: `✅ [${cards.join(", ")}] 카드를 건넵니다.`, components: [] });
    game.pending.resolve(indices);
    return;
  }
}

async function handleSlashCommand(interaction) {
  if (interaction.commandName === "스플렌더") return handleSplendorSlashCommand(interaction);
  if (interaction.commandName !== "달무리") return;
  const channelId = interaction.channelId;
  if (games.has(channelId) || splendorGames.has(channelId)) {
    return interaction.reply({ content: "이미 이 채널에서 게임이 진행 중입니다.", flags: MessageFlags.Ephemeral });
  }
  if (lobbies.has(channelId) || splendorLobbies.has(channelId)) {
    return interaction.reply({
      content: "이미 모집 중인 게임이 있습니다. 아래 메시지에서 참가해주세요.",
      flags: MessageFlags.Ephemeral,
    });
  }
  const lobby = {
    hostId: interaction.user.id,
    channel: interaction.channel,
    players: new Map([[interaction.user.id, { id: interaction.user.id, username: interaction.user.username }]]),
    total: 4,
    maxRank: 12,
  };
  lobbies.set(channelId, lobby);
  await interaction.reply({ embeds: [buildLobbyEmbed(lobby)], components: buildLobbyComponents(lobby) });
}

// ════════════════════════════════════════
// 클라이언트 초기화
// ════════════════════════════════════════

const client = new Client({ intents: [GatewayIntentBits.Guilds] });

client.once(Events.ClientReady, async (c) => {
  console.log(`로그인 완료: ${c.user.tag}`);

  const commands = [
    new SlashCommandBuilder().setName("달무리").setDescription("달무리 게임 참가자를 모집합니다.").toJSON(),
    new SlashCommandBuilder().setName("스플렌더").setDescription("스플렌더 게임 참가자를 모집합니다.").toJSON(),
  ];
  const rest = new REST({ version: "10" }).setToken(config.token);
  try {
    if (config.guildId) {
      await rest.put(Routes.applicationGuildCommands(config.clientId, config.guildId), { body: commands });
      console.log("길드 슬래시 명령어 등록 완료 (즉시 반영됨)");
    } else {
      await rest.put(Routes.applicationCommands(config.clientId), { body: commands });
      console.log("전역 슬래시 명령어 등록 완료 (반영까지 최대 1시간 소요될 수 있음)");
    }
  } catch (err) {
    console.error("슬래시 명령어 등록 실패:", err);
  }
});

client.on(Events.InteractionCreate, async (interaction) => {
  try {
    if (interaction.isChatInputCommand()) {
      await handleSlashCommand(interaction);
    } else if (interaction.isButton()) {
      await handleButton(interaction);
    } else if (interaction.isStringSelectMenu()) {
      await handleSelect(interaction);
    }
  } catch (err) {
    console.error(err);
    if (interaction.isRepliable() && !interaction.replied && !interaction.deferred) {
      await interaction.reply({ content: "오류가 발생했습니다.", flags: MessageFlags.Ephemeral }).catch(() => {});
    }
  }
});

process.on("unhandledRejection", (err) => {
  console.error("Unhandled rejection:", err);
});

if (require.main === module) {
  client.login(config.token);
}

// 테스트용 export (봇 실행 시에는 영향 없음)
module.exports = {
  dealCards,
  nextActive,
  playTrick,
  playRound,
  cardExchange,
  giveCards,
  showRoundResults,
  finishGame,
  runGame,
  buildPublicEmbed,
  autoPickGiveIndices,
  autoPickFromIndices,
  recordExchangeInfo,
  // 스플렌더
  buildSplendorBoardEmbed,
  buildSplendorLobbyEmbed,
  applySplendorAction,
  playSplendorTurn,
  runSplendorGame,
  finishSplendorGame,
  splDiscardUnits,
  handleSplendorButton,
  handleSplendorSelect,
  splendorGames,
};
