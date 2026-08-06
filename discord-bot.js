#!/usr/bin/env node
// -*- coding: utf-8 -*-
/**
 * 달무티 디스코드 봇
 *
 * dalmuti.js의 카드 규칙 로직(Player/AIPlayer 등)을 그대로 재사용하고,
 * 콘솔 입출력 대신 디스코드 버튼/드롭다운으로 진행합니다.
 *
 * 실행 전 준비:
 *   1. npm install
 *   2. discord-config.example.json 을 discord-config.json 으로 복사 후 token/clientId 입력
 *   3. node discord-bot.js
 *   4. 디스코드 채널에서 /달무티 입력
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

const { CARD_NAMES, createDeck, shuffle, getTitle, cardStr, Player, AIPlayer } = require("./dalmuti.js");

const TURN_TIMEOUT_MS = 5 * 60 * 1000; // 5분 무응답 시 자동 진행

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

// ════════════════════════════════════════
// 로비(참가자 모집)
// ════════════════════════════════════════

function buildLobbyEmbed(lobby) {
  const names = [...lobby.players.values()].map((p) => `🙂 ${p.username}`).join("\n") || "-";
  const aiCount = Math.max(0, lobby.total - lobby.players.size);
  return new EmbedBuilder()
    .setTitle("🎴 달무티 - 참가자 모집")
    .setColor(0x57f287)
    .setDescription(
      `아래 **참가하기** 버튼을 눌러 참여하세요.\n호스트(<@${lobby.hostId}>)가 **게임 시작**을 누르면 시작합니다.`
    )
    .addFields(
      { name: `참가자 (${lobby.players.size}명)`, value: names },
      {
        name: "총 인원",
        value: `${lobby.total}명 (사람 ${lobby.players.size}명 + 부족한 자리는 AI ${aiCount}명이 채웁니다)`,
      }
    );
}

function buildLobbyComponents(lobby) {
  const totalSelect = new StringSelectMenuBuilder()
    .setCustomId("lobby_total")
    .setPlaceholder(`총 인원: ${lobby.total}명 (호스트만 변경 가능)`)
    .addOptions([4, 5, 6, 7, 8].map((n) => ({ label: `${n}명`, value: String(n), default: n === lobby.total })));
  const row1 = new ActionRowBuilder().addComponents(totalSelect);
  const row2 = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId("lobby_join").setLabel("참가하기").setStyle(ButtonStyle.Success),
    new ButtonBuilder().setCustomId("lobby_leave").setLabel("나가기").setStyle(ButtonStyle.Secondary),
    new ButtonBuilder().setCustomId("lobby_start").setLabel("게임 시작").setStyle(ButtonStyle.Primary)
  );
  return [row1, row2];
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

  const game = {
    channel: lobby.channel,
    hostId: lobby.hostId,
    players,
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
function waitForPlayerAction(game, player, kind, data, onTimeout) {
  return new Promise((resolve) => {
    let done = false;
    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      game.pending = null;
      resolve(onTimeout ? onTimeout() : null);
    }, TURN_TIMEOUT_MS);

    game.pending = {
      playerId: player.discordId,
      player,
      kind,
      data,
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
    }, TURN_TIMEOUT_MS);

    game.pending = {
      playerId: game.hostId,
      kind: "continue",
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

// ════════════════════════════════════════
// 화면(상태 메시지) 렌더링
// ════════════════════════════════════════

function buildPublicEmbed(game, opts = {}) {
  const n = game.players.length;
  const lines = [];
  for (let i = 0; i < n; i++) {
    const p = game.players[i];
    const isAI = p instanceof AIPlayer;
    const tag = isAI ? "🤖" : "🙂";
    const marker = opts.currentIdx === i ? " ◀ **차례**" : "";
    const status = p.finished ? `✅ ${getTitle(p.finishOrder, n)}` : `카드 ${p.hand.length}장`;
    lines.push(`${tag} **${p.name}** — ${status}${marker}`);
  }

  const embed = new EmbedBuilder()
    .setTitle(`🎴 달무티 - 라운드 ${game.roundNum}`)
    .setColor(0x5865f2)
    .addFields({ name: "플레이어", value: lines.join("\n") || "-" });

  if (opts.tableRank !== undefined && opts.tableRank !== null) {
    embed.addFields({
      name: "바닥",
      value: `[${cardStr(opts.tableRank)}] ${CARD_NAMES[opts.tableRank]} × ${opts.tableCount}장 (${opts.tablePlayerName})`,
    });
  } else {
    embed.addFields({ name: "바닥", value: "비어있음 (선)" });
  }

  if (game.log.length > 0) {
    embed.addFields({ name: "진행 로그", value: game.log.slice(-10).join("\n").slice(0, 1024) });
  }
  return embed;
}

function buildActionRow(turnKind) {
  const row = new ActionRowBuilder();
  if (turnKind) {
    const label = turnKind === "give" ? "카드 선택하기" : "카드 내기";
    row.addComponents(new ButtonBuilder().setCustomId("act_play").setLabel(label).setStyle(ButtonStyle.Primary));
    if (turnKind === "follow") {
      row.addComponents(new ButtonBuilder().setCustomId("act_pass").setLabel("패스").setStyle(ButtonStyle.Secondary));
    }
  }
  if (turnKind === "continue") {
    row.addComponents(
      new ButtonBuilder().setCustomId("cont_yes").setLabel("다음 라운드").setStyle(ButtonStyle.Success),
      new ButtonBuilder().setCustomId("cont_no").setLabel("게임 종료").setStyle(ButtonStyle.Danger)
    );
  }
  row.addComponents(new ButtonBuilder().setCustomId("hand_view").setLabel("내 패 보기").setStyle(ButtonStyle.Secondary));
  return row;
}

async function postStatus(game, embed, rows) {
  const payload = { embeds: [embed], components: rows };
  try {
    if (game.statusMessage) {
      game.statusMessage = await game.statusMessage.edit(payload);
      return;
    }
  } catch (e) {
    // 메시지가 삭제되었거나 편집 실패 시 새로 보냄
  }
  game.statusMessage = await game.channel.send(payload);
}

async function postLog(game, opts = {}) {
  await postStatus(game, buildPublicEmbed(game, opts), [buildActionRow(null)]);
}

async function showTurn(game, currentIdx, tableRank, tableCount, tablePlayerName, turnKind) {
  const embed = buildPublicEmbed(game, { currentIdx, tableRank, tableCount, tablePlayerName });
  await postStatus(game, embed, [buildActionRow(turnKind)]);
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
    label: `[${r}] ${CARD_NAMES[r]}`,
    description: `보유 ${counts[r]}장${jokers > 0 ? ` (+조커 ${jokers}장 사용 가능)` : ""}`,
    value: String(r),
  }));
  const select = new StringSelectMenuBuilder()
    .setCustomId("sel_lead_rank")
    .setPlaceholder("낼 카드 숫자를 선택하세요")
    .addOptions(options.slice(0, 25));
  await interaction.reply({
    content: "낼 카드의 숫자를 선택하세요.",
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
      content: "낼 수 있는 카드가 없습니다. 패스를 눌러주세요.",
      flags: MessageFlags.Ephemeral,
    });
    return;
  }
  game.pending.validPlays = plays;
  const options = plays.map((p, i) => ({
    label: `[${p.rank}] ${CARD_NAMES[p.rank]} × ${p.count}장${p.jokerCount > 0 ? ` (조커 ${p.jokerCount})` : ""}`,
    value: String(i),
  }));
  const select = new StringSelectMenuBuilder()
    .setCustomId("sel_follow")
    .setPlaceholder("낼 카드를 선택하세요")
    .addOptions(options.slice(0, 25));
  await interaction.reply({
    content: `[${reqRank}]보다 낮은 숫자로 ${reqCount}장을 내세요.`,
    components: [new ActionRowBuilder().addComponents(select)],
    flags: MessageFlags.Ephemeral,
  });
}

async function openGiveSelect(interaction, game) {
  const player = game.pending.player;
  const { count, receiverName } = game.pending.data;
  const options = player.hand.map((card, i) => ({
    label: card === 13 ? "★ 조커" : `[${card}] ${CARD_NAMES[card]}`,
    value: String(i),
  }));
  const select = new StringSelectMenuBuilder()
    .setCustomId("sel_give")
    .setPlaceholder(`${receiverName}에게 줄 카드 ${count}장을 선택하세요`)
    .setMinValues(count)
    .setMaxValues(count)
    .addOptions(options);
  await interaction.reply({
    content: `${receiverName}에게 줄 카드 ${count}장을 선택하세요.`,
    components: [new ActionRowBuilder().addComponents(select)],
    flags: MessageFlags.Ephemeral,
  });
}

async function showHand(interaction) {
  const game = games.get(interaction.channelId);
  if (!game) return interaction.reply({ content: "진행 중인 게임이 없습니다.", flags: MessageFlags.Ephemeral });
  const player = game.players.find((p) => p.discordId === interaction.user.id);
  if (!player) {
    return interaction.reply({ content: "이 게임에 참가하지 않으셨습니다.", flags: MessageFlags.Ephemeral });
  }
  if (player.hand.length === 0) {
    return interaction.reply({ content: "패가 없습니다 (완료했거나 아직 배분 전입니다).", flags: MessageFlags.Ephemeral });
  }
  const counts = player.counts();
  const ranks = Object.keys(counts).map(Number).sort((a, b) => a - b);
  const lines = ranks.map((r) => (r === 13 ? `★ 조커 × ${counts[r]}` : `[${r}] ${CARD_NAMES[r]} × ${counts[r]}`));
  await interaction.reply({
    content: `**${player.name}님의 패** (${player.hand.length}장)\n${lines.join("\n")}`,
    flags: MessageFlags.Ephemeral,
  });
}

// ════════════════════════════════════════
// 게임 진행 (라운드/트릭/카드교환) - dalmuti.js의 규칙 로직을 재사용
// ════════════════════════════════════════

function dealCards(game) {
  const deck = shuffle(createDeck());
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
  if (!player.canPlay(reqCount, reqRank)) {
    return null;
  }
  const promise = waitForPlayerAction(game, player, "follow", { reqRank, reqCount }, () => {
    logEvent(game, `⏰ ${player.name}님이 시간 내에 응답하지 않아 자동 패스합니다.`);
    return null;
  });
  await showTurn(game, currentIdx, reqRank, reqCount, trickWinnerName, "follow");
  return promise;
}

async function playTrick(game, leaderIdx) {
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
  logEvent(game, `▶ **${leader.name}**: [${play.rank}] ${CARD_NAMES[play.rank]} × ${play.count}장${jokerStr}`);

  let currentRank = play.rank;
  let currentCount = play.count;
  let trickWinnerIdx = leaderIdx;

  if (!leader.hasCards()) {
    leader.finished = true;
    leader.finishOrder = game.finishedPlayers.length;
    game.finishedPlayers.push(leaderIdx);
    logEvent(game, `🎉 **${leader.name}** 완료! → ${getTitle(leader.finishOrder, n)}`);
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
      logEvent(game, `⏭ **${player.name}**: 패스`);
      passedPlayers.add(currentIdx);
    } else {
      player.removeCards(result.rank, result.count, result.jokerCount);
      const jStr = result.jokerCount > 0 ? ` (조커 ${result.jokerCount}장 포함)` : "";
      logEvent(game, `▶ **${player.name}**: [${result.rank}] ${CARD_NAMES[result.rank]} × ${result.count}장${jStr}`);
      currentRank = result.rank;
      trickWinnerIdx = currentIdx;
      passedPlayers.clear();

      if (!player.hasCards()) {
        player.finished = true;
        player.finishOrder = game.finishedPlayers.length;
        game.finishedPlayers.push(currentIdx);
        logEvent(game, `🎉 **${player.name}** 완료! → ${getTitle(player.finishOrder, n)}`);
      }
    }
    currentIdx = nextActive(game, currentIdx);
  }

  const activeLeft = game.players.filter((p) => !p.finished);
  if (activeLeft.length > 1 && !game.players[trickWinnerIdx].finished) {
    logEvent(game, `🏆 **${game.players[trickWinnerIdx].name}**님이 트릭 승리!`);
  }
  await postLog(game);

  if (!game.players[trickWinnerIdx].finished) return trickWinnerIdx;
  return nextActive(game, trickWinnerIdx);
}

async function giveCards(game, giver, receiver, count) {
  let indices;
  if (giver instanceof AIPlayer) {
    indices = autoPickGiveIndices(giver, count);
  } else {
    const giverIdx = game.players.indexOf(giver);
    const promise = waitForPlayerAction(game, giver, "give", { count, receiverName: receiver.name }, () => {
      logEvent(game, `⏰ ${giver.name}님이 시간 내에 선택하지 않아 자동으로 진행합니다.`);
      return autoPickGiveIndices(giver, count);
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
  logEvent(game, `${giver.name} → ${receiver.name}: [${given.join(", ")}] 전달`);
}

async function cardExchange(game) {
  const n = game.players.length;
  if (n < 4 || game.rankings.length === 0) return;

  const greatDalmuti = game.players[game.rankings[0]];
  const dalmuti = game.players[game.rankings[1]];
  const peon = game.players[game.rankings[n - 2]];
  const greatPeon = game.players[game.rankings[n - 1]];

  const jokerCount = greatPeon.hand.filter((c) => c === 13).length;
  if (jokerCount === 2) {
    logEvent(game, `🔥 혁명! **${greatPeon.name}**이(가) 조커 2장 보유! 카드 교환이 취소됩니다!`);
    await postLog(game);
    return;
  }

  logEvent(game, `📜 카드 교환 시작`);

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
  logEvent(game, `${greatPeon.name}(대빈민) → ${greatDalmuti.name}(대달무티): 최고 카드 2장 헌납 [${bestCards.join(", ")}]`);

  await giveCards(game, greatDalmuti, greatPeon, 2);

  peon.sortHand();
  let bestCard = peon.hand.find((c) => c !== 13);
  if (bestCard === undefined && peon.hand.length > 0) bestCard = peon.hand[0];
  if (bestCard !== undefined) {
    const idx = peon.hand.indexOf(bestCard);
    peon.hand.splice(idx, 1);
    dalmuti.hand.push(bestCard);
    logEvent(game, `${peon.name}(빈민) → ${dalmuti.name}(달무티): 최고 카드 1장 [${bestCard}]`);
  }

  await giveCards(game, dalmuti, peon, 1);

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
    logEvent(game, `${game.players[leaderIdx].name}이(가) [1] 달무티 카드를 갖고 있어 선으로 시작!`);
  } else {
    logEvent(game, `${game.players[leaderIdx].name}(대달무티)이(가) 선으로 시작!`);
  }
  await postLog(game);

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
// 인터랙션 라우팅
// ════════════════════════════════════════

async function handleButton(interaction) {
  const { customId } = interaction;

  if (customId === "lobby_join") return lobbyJoin(interaction);
  if (customId === "lobby_leave") return lobbyLeave(interaction);
  if (customId === "lobby_start") return lobbyStart(interaction);
  if (customId === "hand_view") return showHand(interaction);

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
  if (interaction.customId === "lobby_total") return lobbySetTotal(interaction);

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
      content: `[${rank}] ${CARD_NAMES[rank]} 선택됨. 몇 장을 내시겠습니까?`,
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
    await interaction.update({ content: `✅ [${rank}] ${CARD_NAMES[rank]} × ${count}장 냅니다.`, components: [] });
    game.pending.resolve({ rank, count, jokerCount });
    return;
  }

  if (interaction.customId === "sel_follow") {
    const idx = parseInt(interaction.values[0]);
    const play = game.pending.validPlays[idx];
    await interaction.update({
      content: `✅ [${play.rank}] ${CARD_NAMES[play.rank]} × ${play.count}장 냅니다.`,
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
  if (interaction.commandName !== "달무티") return;
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
  await interaction.reply({ embeds: [buildLobbyEmbed(lobby)], components: buildLobbyComponents(lobby) });
}

// ════════════════════════════════════════
// 클라이언트 초기화
// ════════════════════════════════════════

const client = new Client({ intents: [GatewayIntentBits.Guilds] });

client.once(Events.ClientReady, async (c) => {
  console.log(`로그인 완료: ${c.user.tag}`);

  const commands = [
    new SlashCommandBuilder().setName("달무티").setDescription("달무티 게임 참가자를 모집합니다.").toJSON(),
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
};
