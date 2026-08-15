#!/usr/bin/env node
// -*- coding: utf-8 -*-
/**
 * 스플렌더 (Splendor) 카드 게임 - 규칙 엔진
 *
 * 콘솔/디스코드 어디서든 재사용할 수 있도록 순수 게임 로직만 담당합니다.
 * (렌더링/입출력은 discord-bot.js 에서 처리)
 */

// ════════════════════════════════════════
// 상수
// ════════════════════════════════════════

const COLORS = ["white", "blue", "green", "red", "black"];

const GEM_INFO = {
  white: { emoji: "⚪", label: "하양(다이아몬드)" },
  blue: { emoji: "🔵", label: "파랑(사파이어)" },
  green: { emoji: "🟢", label: "초록(에메랄드)" },
  red: { emoji: "🔴", label: "빨강(루비)" },
  black: { emoji: "⚫", label: "검정(오닉스)" },
  gold: { emoji: "🟡", label: "금(만능)" },
};

const BANK_BY_PLAYER_COUNT = { 2: 4, 3: 5, 4: 7 };
const GOLD_COUNT = 5;
const WIN_POINTS = 15;
const MAX_TOKENS = 10;
const MAX_RESERVED = 3;

// ════════════════════════════════════════
// 카드/귀족 풀 생성 (결정론적 시드 - 매 프로세스 실행마다 동일한 카드 구성)
// ════════════════════════════════════════

function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function otherColors(color) {
  return COLORS.filter((c) => c !== color);
}

/** 티어별 카드 생성 파라미터에 맞춰 8/6/4장씩(색상당) 카드를 만듦 */
function buildTierCards(rng, tier, color, templates) {
  const others = otherColors(color);
  return templates.map((tpl, i) => {
    const cost = {};
    others.forEach((c, idx) => {
      if (tpl.cost[idx] > 0) cost[c] = tpl.cost[idx];
    });
    return {
      id: `t${tier}-${color}-${i}`,
      tier,
      color,
      points: tpl.points,
      cost,
    };
  });
}

// 티어1: 색상당 8장, 총 비용 3~4, 0~1점
const TIER1_TEMPLATES = [
  { cost: [1, 1, 1, 0], points: 0 },
  { cost: [0, 2, 0, 1], points: 0 },
  { cost: [2, 0, 1, 0], points: 0 },
  { cost: [0, 0, 2, 2], points: 0 },
  { cost: [1, 1, 0, 1], points: 0 },
  { cost: [3, 0, 0, 0], points: 0 },
  { cost: [2, 2, 0, 0], points: 0 },
  { cost: [4, 0, 0, 0], points: 1 },
];

// 티어2: 색상당 6장, 총 비용 6~7, 1~3점
const TIER2_TEMPLATES = [
  { cost: [3, 2, 0, 0], points: 1 },
  { cost: [0, 3, 2, 2], points: 1 },
  { cost: [2, 0, 0, 5], points: 2 },
  { cost: [5, 0, 2, 0], points: 2 },
  { cost: [0, 4, 0, 3], points: 2 },
  { cost: [6, 0, 0, 0], points: 3 },
];

// 티어3: 색상당 4장, 총 비용 8~10, 3~5점
const TIER3_TEMPLATES = [
  { cost: [3, 3, 3, 5], points: 3 },
  { cost: [7, 0, 0, 3], points: 4 },
  { cost: [0, 6, 3, 3], points: 4 },
  { cost: [7, 3, 0, 0], points: 5 },
];

function createCardPool() {
  const rng = mulberry32(20240815);
  const pool = { 1: [], 2: [], 3: [] };
  for (const color of COLORS) {
    pool[1].push(...buildTierCards(rng, 1, color, TIER1_TEMPLATES));
    pool[2].push(...buildTierCards(rng, 2, color, TIER2_TEMPLATES));
    pool[3].push(...buildTierCards(rng, 3, color, TIER3_TEMPLATES));
  }
  return pool;
}

// 10개 귀족 (5명 플레이어+1 규칙에 맞춰 필요한 만큼 무작위로 뽑아 사용)
function createNoblePool() {
  const triples = [
    ["white", "blue", "green"],
    ["blue", "green", "red"],
    ["green", "red", "black"],
    ["red", "black", "white"],
    ["black", "white", "blue"],
  ];
  const pairs = [
    ["white", "black"],
    ["blue", "white"],
    ["green", "blue"],
    ["red", "green"],
    ["black", "red"],
  ];
  const nobles = [];
  triples.forEach((cs, i) => {
    const cost = {};
    cs.forEach((c) => (cost[c] = 3));
    nobles.push({ id: `noble-triple-${i}`, points: 3, cost });
  });
  pairs.forEach((cs, i) => {
    const cost = {};
    cs.forEach((c) => (cost[c] = 4));
    nobles.push({ id: `noble-pair-${i}`, points: 3, cost });
  });
  return nobles;
}

const CARD_POOL = createCardPool();
const NOBLE_POOL = createNoblePool();

// ════════════════════════════════════════
// 유틸
// ════════════════════════════════════════

function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function zeroTokens() {
  return { white: 0, blue: 0, green: 0, red: 0, black: 0, gold: 0 };
}

function tokenTotal(tokens) {
  return COLORS.reduce((s, c) => s + tokens[c], 0) + tokens.gold;
}

/** 카드 구매 시 보너스 적용 후 실질 비용 */
function effectiveCost(card, player) {
  const cost = {};
  for (const c of COLORS) {
    const need = (card.cost[c] || 0) - (player.bonuses[c] || 0);
    if (need > 0) cost[c] = need;
  }
  return cost;
}

/** 실질 비용을 보유 토큰(색상 우선, 부족분은 금)으로 지불 가능한지 + 필요한 지불 내역 계산 */
function computePayment(card, player) {
  const cost = effectiveCost(card, player);
  const payment = zeroTokens();
  let goldNeeded = 0;
  for (const c of COLORS) {
    const need = cost[c] || 0;
    if (need === 0) continue;
    const have = player.tokens[c];
    const useColored = Math.min(need, have);
    payment[c] = useColored;
    goldNeeded += need - useColored;
  }
  if (goldNeeded > player.tokens.gold) return null;
  payment.gold = goldNeeded;
  return payment;
}

function canAfford(card, player) {
  return computePayment(card, player) !== null;
}

// ════════════════════════════════════════
// 게임 생성
// ════════════════════════════════════════

function makePlayerState(p) {
  return {
    id: p.id,
    name: p.name,
    isAI: !!p.isAI,
    discordId: p.discordId || null,
    tokens: zeroTokens(),
    bonuses: zeroTokens(),
    cards: [],
    reserved: [],
    nobles: [],
    points: 0,
  };
}

function newGame(players) {
  const n = players.length;
  if (n < 2 || n > 4) throw new Error("스플렌더는 2~4인 게임입니다.");

  const decks = { 1: shuffle([...CARD_POOL[1]]), 2: shuffle([...CARD_POOL[2]]), 3: shuffle([...CARD_POOL[3]]) };
  const board = { 1: [], 2: [], 3: [] };
  for (const tier of [1, 2, 3]) {
    for (let i = 0; i < 4; i++) board[tier].push(decks[tier].pop() || null);
  }

  const tokens = zeroTokens();
  for (const c of COLORS) tokens[c] = BANK_BY_PLAYER_COUNT[n];
  tokens.gold = GOLD_COUNT;

  const nobles = shuffle([...NOBLE_POOL]).slice(0, n + 1);

  return {
    players: players.map(makePlayerState),
    board,
    decks,
    tokens,
    nobles,
    currentIdx: 0,
    turnNumber: 1,
    finalRound: false,
    finalRoundRemaining: 0,
    winners: null,
    log: [],
  };
}

function logEvent(game, text) {
  game.log.push(text);
}

// ════════════════════════════════════════
// 액션: 토큰 가져오기
// ════════════════════════════════════════

function canTake3(game, colors) {
  if (!Array.isArray(colors) || colors.length < 1 || colors.length > 3) return false;
  const set = new Set(colors);
  if (set.size !== colors.length) return false;
  for (const c of colors) {
    if (!COLORS.includes(c)) return false;
    if (game.tokens[c] < 1) return false;
  }
  return true;
}

function canTake2(game, color) {
  return COLORS.includes(color) && game.tokens[color] >= 4;
}

function doTake3(game, playerIdx, colors) {
  if (!canTake3(game, colors)) return { ok: false, error: "선택한 토큰을 가져올 수 없습니다." };
  const player = game.players[playerIdx];
  for (const c of colors) {
    game.tokens[c]--;
    player.tokens[c]++;
  }
  logEvent(game, `${player.name}: 토큰 ${colors.map((c) => GEM_INFO[c].emoji).join(" ")} 획득`);
  return { ok: true };
}

function doTake2(game, playerIdx, color) {
  if (!canTake2(game, color)) return { ok: false, error: "해당 색상은 2개를 가져올 수 없습니다 (은행에 4개 미만)." };
  const player = game.players[playerIdx];
  game.tokens[color] -= 2;
  player.tokens[color] += 2;
  logEvent(game, `${player.name}: 토큰 ${GEM_INFO[color].emoji}${GEM_INFO[color].emoji} 획득`);
  return { ok: true };
}

// ════════════════════════════════════════
// 액션: 카드 예약
// ════════════════════════════════════════

function doReserveBoard(game, playerIdx, tier, slotIdx) {
  const player = game.players[playerIdx];
  if (player.reserved.length >= MAX_RESERVED) return { ok: false, error: "이미 예약 카드가 3장입니다." };
  const card = game.board[tier][slotIdx];
  if (!card) return { ok: false, error: "해당 자리에 카드가 없습니다." };
  game.board[tier][slotIdx] = game.decks[tier].pop() || null;
  player.reserved.push(card);
  let gotGold = false;
  if (game.tokens.gold > 0) {
    game.tokens.gold--;
    player.tokens.gold++;
    gotGold = true;
  }
  logEvent(game, `${player.name}: [T${tier}] 카드 예약${gotGold ? " (+🟡 금 1개)" : ""}`);
  return { ok: true, card, gotGold };
}

function doReserveBlind(game, playerIdx, tier) {
  const player = game.players[playerIdx];
  if (player.reserved.length >= MAX_RESERVED) return { ok: false, error: "이미 예약 카드가 3장입니다." };
  const card = game.decks[tier].pop();
  if (!card) return { ok: false, error: "해당 티어의 덱이 비어 있습니다." };
  player.reserved.push(card);
  let gotGold = false;
  if (game.tokens.gold > 0) {
    game.tokens.gold--;
    player.tokens.gold++;
    gotGold = true;
  }
  logEvent(game, `${player.name}: [T${tier}] 덱에서 비공개로 카드 예약${gotGold ? " (+🟡 금 1개)" : ""}`);
  return { ok: true, card, gotGold };
}

// ════════════════════════════════════════
// 액션: 카드 구매
// ════════════════════════════════════════

function applyPayment(game, player, payment) {
  for (const c of COLORS) {
    player.tokens[c] -= payment[c];
    game.tokens[c] += payment[c];
  }
  player.tokens.gold -= payment.gold;
  game.tokens.gold += payment.gold;
}

function grantCard(player, card) {
  player.cards.push(card);
  player.bonuses[card.color] = (player.bonuses[card.color] || 0) + 1;
  player.points += card.points;
}

function doBuyBoard(game, playerIdx, tier, slotIdx) {
  const player = game.players[playerIdx];
  const card = game.board[tier][slotIdx];
  if (!card) return { ok: false, error: "해당 자리에 카드가 없습니다." };
  const payment = computePayment(card, player);
  if (!payment) return { ok: false, error: "토큰이 부족해 구매할 수 없습니다." };
  applyPayment(game, player, payment);
  game.board[tier][slotIdx] = game.decks[tier].pop() || null;
  grantCard(player, card);
  logEvent(game, `${player.name}: [T${tier}] 카드 구매 (+${card.points}점)`);
  return { ok: true, card, payment };
}

function doBuyReserved(game, playerIdx, reservedIdx) {
  const player = game.players[playerIdx];
  const card = player.reserved[reservedIdx];
  if (!card) return { ok: false, error: "예약 카드가 없습니다." };
  const payment = computePayment(card, player);
  if (!payment) return { ok: false, error: "토큰이 부족해 구매할 수 없습니다." };
  applyPayment(game, player, payment);
  player.reserved.splice(reservedIdx, 1);
  grantCard(player, card);
  logEvent(game, `${player.name}: 예약 카드 구매 (+${card.points}점)`);
  return { ok: true, card, payment };
}

// ════════════════════════════════════════
// 토큰 초과 반납
// ════════════════════════════════════════

function overflowCount(player) {
  return Math.max(0, tokenTotal(player.tokens) - MAX_TOKENS);
}

function discardTokens(game, playerIdx, colorCounts) {
  const player = game.players[playerIdx];
  const need = overflowCount(player);
  let sum = 0;
  for (const c of [...COLORS, "gold"]) {
    const n = colorCounts[c] || 0;
    if (n < 0 || n > player.tokens[c]) return { ok: false, error: "보유하지 않은 토큰을 반납할 수 없습니다." };
    sum += n;
  }
  if (sum !== need) return { ok: false, error: `정확히 ${need}개를 반납해야 합니다.` };
  for (const c of [...COLORS, "gold"]) {
    const n = colorCounts[c] || 0;
    player.tokens[c] -= n;
    game.tokens[c] += n;
  }
  logEvent(game, `${player.name}: 토큰 ${need}개 반납`);
  return { ok: true };
}

/** 반납 없이 자동으로(AI/시간초과) 가장 남는 토큰부터 반납 */
function autoDiscardPlan(player) {
  const need = overflowCount(player);
  const plan = zeroTokens();
  let remaining = need;
  const order = [...COLORS].sort((a, b) => {
    const excessA = player.tokens[a] - (player.bonuses[a] ? 1 : 2);
    const excessB = player.tokens[b] - (player.bonuses[b] ? 1 : 2);
    return excessB - excessA;
  });
  for (const c of order) {
    while (remaining > 0 && player.tokens[c] - plan[c] > 0) {
      plan[c]++;
      remaining--;
    }
    if (remaining === 0) break;
  }
  if (remaining > 0) {
    // 색상 토큰으로 부족하면 마지막으로 금 반납 (거의 발생하지 않음)
    while (remaining > 0 && player.tokens.gold - plan.gold > 0) {
      plan.gold++;
      remaining--;
    }
  }
  return plan;
}

// ════════════════════════════════════════
// 귀족 방문
// ════════════════════════════════════════

function getEligibleNobles(game, playerIdx) {
  const player = game.players[playerIdx];
  const eligible = [];
  game.nobles.forEach((noble, idx) => {
    const ok = COLORS.every((c) => (player.bonuses[c] || 0) >= (noble.cost[c] || 0));
    if (ok) eligible.push(idx);
  });
  return eligible;
}

function claimNoble(game, playerIdx, nobleIdx) {
  const player = game.players[playerIdx];
  const noble = game.nobles[nobleIdx];
  if (!noble) return { ok: false, error: "해당 귀족이 없습니다." };
  game.nobles.splice(nobleIdx, 1);
  player.nobles.push(noble);
  player.points += noble.points;
  logEvent(game, `${player.name}: 귀족 방문 (+${noble.points}점)`);
  return { ok: true, noble };
}

// ════════════════════════════════════════
// 라운드 종료/승리 판정
// ════════════════════════════════════════

/** 플레이어의 턴이 완전히 끝난 뒤 호출: 게임 종료 트리거 관리 */
function noteTurnEnded(game, playerIdx) {
  const player = game.players[playerIdx];
  if (!game.finalRound && player.points >= WIN_POINTS) {
    game.finalRound = true;
    game.finalRoundRemaining = game.players.length - 1;
    logEvent(game, `🏁 ${player.name}이(가) ${WIN_POINTS}점을 달성! 이번 라운드가 마지막 라운드입니다.`);
    return game.finalRoundRemaining === 0;
  }
  if (game.finalRound) {
    game.finalRoundRemaining--;
    return game.finalRoundRemaining <= 0;
  }
  return false;
}

function getWinners(game) {
  let best = -1;
  for (const p of game.players) if (p.points > best) best = p.points;
  const topByPoints = game.players.filter((p) => p.points === best);
  let fewestCards = Infinity;
  for (const p of topByPoints) if (p.cards.length < fewestCards) fewestCards = p.cards.length;
  return topByPoints.filter((p) => p.cards.length === fewestCards);
}

function nextIdx(game, idx) {
  return (idx + 1) % game.players.length;
}

// ════════════════════════════════════════
// AI 로직
// ════════════════════════════════════════

function allBoardCards(game) {
  const list = [];
  for (const tier of [1, 2, 3]) {
    game.board[tier].forEach((card, slotIdx) => {
      if (card) list.push({ card, tier, slotIdx });
    });
  }
  return list;
}

function scoreCardForAI(card) {
  // 점수는 비용 대비 높을수록, 총 비용이 낮을수록 좋음
  const costSum = COLORS.reduce((s, c) => s + (card.cost[c] || 0), 0);
  return card.points * 3 - costSum * 0.3 + 1;
}

/** AI가 이번 턴에 할 행동을 고름 */
function chooseAIAction(game, playerIdx) {
  const player = game.players[playerIdx];

  // 1) 살 수 있는 카드 중 가장 좋은 것 구매 (보드 + 예약)
  const buyable = [];
  allBoardCards(game).forEach(({ card, tier, slotIdx }) => {
    if (canAfford(card, player)) buyable.push({ type: "buyBoard", tier, slotIdx, card });
  });
  player.reserved.forEach((card, reservedIdx) => {
    if (canAfford(card, player)) buyable.push({ type: "buyReserved", reservedIdx, card });
  });
  if (buyable.length > 0) {
    buyable.sort((a, b) => scoreCardForAI(b.card) - scoreCardForAI(a.card));
    return buyable[0];
  }

  // 2) 보드 카드 기준으로 가장 부족한 색상 파악
  const need = zeroTokens();
  for (const { card } of allBoardCards(game)) {
    for (const c of COLORS) {
      const deficit = (card.cost[c] || 0) - (player.bonuses[c] || 0) - player.tokens[c];
      if (deficit > 0) need[c] += deficit * (card.tier === 1 ? 1 : card.tier === 2 ? 1.5 : 2);
    }
  }

  // 3) 2개 같은 색 가져오기 (가장 필요한 색이 은행에 4개 이상 있으면)
  const sortedByNeed = [...COLORS].sort((a, b) => need[b] - need[a]);
  for (const c of sortedByNeed) {
    if (need[c] > 0 && canTake2(game, c) && tokenTotal(player.tokens) <= MAX_TOKENS - 2) {
      return { type: "take2", color: c };
    }
  }

  // 4) 서로 다른 색 최대 3개
  const takeable = COLORS.filter((c) => game.tokens[c] > 0);
  takeable.sort((a, b) => need[b] - need[a]);
  const picked = takeable.slice(0, 3);
  if (picked.length > 0) {
    return { type: "take3", colors: picked };
  }

  // 5) 예약 (은행에 토큰이 거의 없을 때) - 가장 점수 높은 보드 카드 예약
  if (player.reserved.length < MAX_RESERVED) {
    const candidates = allBoardCards(game).sort((a, b) => scoreCardForAI(b.card) - scoreCardForAI(a.card));
    if (candidates.length > 0) {
      return { type: "reserveBoard", tier: candidates[0].tier, slotIdx: candidates[0].slotIdx };
    }
  }

  return { type: "pass" };
}

function chooseAINoble(game, playerIdx, eligibleIdxs) {
  // 여러 귀족이 가능하면 임의로 첫 번째 선택 (모두 3점으로 동일)
  return eligibleIdxs[0];
}

module.exports = {
  COLORS,
  GEM_INFO,
  WIN_POINTS,
  MAX_TOKENS,
  MAX_RESERVED,
  CARD_POOL,
  NOBLE_POOL,
  newGame,
  logEvent,
  canTake3,
  canTake2,
  doTake3,
  doTake2,
  doReserveBoard,
  doReserveBlind,
  doBuyBoard,
  doBuyReserved,
  computePayment,
  canAfford,
  effectiveCost,
  overflowCount,
  discardTokens,
  autoDiscardPlan,
  getEligibleNobles,
  claimNoble,
  noteTurnEnded,
  getWinners,
  nextIdx,
  tokenTotal,
  chooseAIAction,
  chooseAINoble,
  allBoardCards,
};
