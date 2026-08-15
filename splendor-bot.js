#!/usr/bin/env node
// -*- coding: utf-8 -*-
/**
 * 스플렌더 디스코드 봇 (달무리와 완전히 독립적으로 실행 가능)
 *
 * splendor.js의 규칙 로직만 사용하며, dalmuti.js에 의존하지 않습니다.
 *
 * 실행 전 준비:
 *   1. npm install
 *   2. discord-config.example.json 을 discord-config.json 으로 복사 후 token/clientId 입력
 *   3. node splendor-bot.js  (또는 npm run splendor)
 *   4. 디스코드 채널에서 /스플렌더 입력
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

const Spl = require("./splendor.js");

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

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

// ════════════════════════════════════════
// 상태 (채널 단위)
// ════════════════════════════════════════

const lobbies = new Map(); // channelId -> lobby
const games = new Map(); // channelId -> game

// ════════════════════════════════════════
// 대기(입력) 헬퍼
// ════════════════════════════════════════

/** 특정 플레이어의 행동을 기다림. 시간 초과 시 onTimeout() 결과로 자동 진행 */
function waitForPlayerAction(game, player, kind, data, onTimeout, timeoutMs = SPLENDOR_TURN_TIMEOUT_MS) {
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

// 디스코드 "ansi" 코드블록에서 지원하는 색상 (데스크톱 클라이언트에서 실제 색으로 렌더링됨)
const ANSI = {
  reset: "[0m",
  bold: "[1m",
  dim: "[2m",
  boldYellow: "[1;33m",
  boldGreen: "[1;32m",
  boldCyan: "[1;36m",
  boldMagenta: "[1;35m",
};

function ansiBlock(text) {
  return "```ansi\n" + text + "\n```";
}

// ════════════════════════════════════════
// 로비(참가자 모집)
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
  const lobby = lobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (lobby.players.size >= 4) {
    return interaction.reply({ content: "최대 4명까지 참가할 수 있습니다.", flags: MessageFlags.Ephemeral });
  }
  lobby.players.set(interaction.user.id, { id: interaction.user.id, username: interaction.user.username });
  if (lobby.players.size > lobby.total) lobby.total = lobby.players.size;
  await refreshSplendorLobby(interaction, lobby);
}

async function splLobbyLeave(interaction) {
  const lobby = lobbies.get(interaction.channelId);
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
  const lobby = lobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (interaction.user.id !== lobby.hostId) {
    return interaction.reply({ content: "호스트만 인원 수를 바꿀 수 있습니다.", flags: MessageFlags.Ephemeral });
  }
  const val = parseInt(interaction.values[0]);
  lobby.total = Math.max(val, lobby.players.size, 2);
  await refreshSplendorLobby(interaction, lobby);
}

async function splLobbyStart(interaction) {
  const lobby = lobbies.get(interaction.channelId);
  if (!lobby) return interaction.reply({ content: "모집 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  if (interaction.user.id !== lobby.hostId) {
    return interaction.reply({ content: "호스트만 게임을 시작할 수 있습니다.", flags: MessageFlags.Ephemeral });
  }

  lobbies.delete(interaction.channelId);
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
  games.set(interaction.channelId, game);

  runSplendorGame(game).catch((err) => {
    console.error(err);
    game.channel.send("⚠️ 게임 중 오류가 발생하여 게임을 종료합니다.").catch(() => {});
    games.delete(interaction.channelId);
  });
}

// ════════════════════════════════════════
// 화면(상태 메시지) 렌더링
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
// 사람 입력을 여는 select 메뉴들
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
// 게임 진행
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
  games.delete(game.channel.id);
}

// ════════════════════════════════════════
// 인터랙션 라우팅
// ════════════════════════════════════════

async function handleButton(interaction) {
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
    const game = games.get(interaction.channelId);
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

async function handleSelect(interaction) {
  if (interaction.customId === "sp_lobby_total") return splLobbySetTotal(interaction);

  const game = games.get(interaction.channelId);
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

async function handleSlashCommand(interaction) {
  if (interaction.commandName !== "스플렌더") return;
  const channelId = interaction.channelId;
  if (games.has(channelId)) {
    return interaction.reply({ content: "이미 이 채널에서 게임이 진행 중입니다.", flags: MessageFlags.Ephemeral });
  }
  if (lobbies.has(channelId)) {
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
  lobbies.set(channelId, lobby);
  await interaction.reply({ embeds: [buildSplendorLobbyEmbed(lobby)], components: buildSplendorLobbyComponents(lobby) });
}

// ════════════════════════════════════════
// 클라이언트 초기화
// ════════════════════════════════════════

const client = new Client({ intents: [GatewayIntentBits.Guilds] });

client.once(Events.ClientReady, async (c) => {
  console.log(`로그인 완료: ${c.user.tag}`);

  const commands = [
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
  lobbies,
  games,
  buildSplendorBoardEmbed,
  buildSplendorLobbyEmbed,
  applySplendorAction,
  playSplendorTurn,
  runSplendorGame,
  finishSplendorGame,
  splDiscardUnits,
  handleButton,
  handleSelect,
  handleSlashCommand,
};
