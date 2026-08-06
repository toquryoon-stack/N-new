#!/usr/bin/env node
// -*- coding: utf-8 -*-
/**
 * 달무티 (The Great Dalmuti) - 콘솔 카드 게임
 *
 * Node.js 콘솔 기반 달무티 카드 게임
 * - 혼자 vs AI / 로컬 멀티 / 혼합 모드 지원
 * - 네트워크 멀티플레이 (같은 Wi-Fi/공유기에서 각자 PC로 접속) 지원
 * - 4~8인 플레이 가능
 */

const readline = require("readline");
const net = require("net");
const os = require("os");

// ════════════════════════════════════════
// 상수
// ════════════════════════════════════════

const CARD_NAMES = {
  1: "달무티", 2: "대주교", 3: "원수", 4: "남작부인",
  5: "수녀원장", 6: "기사", 7: "재봉사", 8: "석공",
  9: "요리사", 10: "양치기", 11: "농부", 12: "빈민",
  13: "조커"
};

const C = {
  RESET: "\x1b[0m",
  BOLD: "\x1b[1m",
  DIM: "\x1b[2m",
  RED: "\x1b[91m",
  GREEN: "\x1b[92m",
  YELLOW: "\x1b[93m",
  BLUE: "\x1b[94m",
  MAGENTA: "\x1b[95m",
  CYAN: "\x1b[96m",
  WHITE: "\x1b[97m",
};

const CLEAR_CODE = "\x1b[2J\x1b[H";
const DEFAULT_PORT = 7777;

// ════════════════════════════════════════
// 유틸리티
// ════════════════════════════════════════

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
});

function ask(prompt) {
  return new Promise((resolve) => {
    rl.question(prompt, (answer) => resolve(answer.trim()));
  });
}

function clear() {
  process.stdout.write(CLEAR_CODE);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 카드 80장 덱 생성 */
function createDeck() {
  const deck = [];
  for (let rank = 1; rank <= 12; rank++) {
    for (let i = 0; i < rank; i++) deck.push(rank);
  }
  deck.push(13, 13); // 조커 2장
  return deck;
}

/** Fisher-Yates 셔플 */
function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

/** 카드 배열 → 랭크별 카운트 맵 */
function countCards(hand) {
  const counts = {};
  for (const card of hand) {
    counts[card] = (counts[card] || 0) + 1;
  }
  return counts;
}

/** 패 요약 출력 문자열 */
function handSummary(hand) {
  const counts = countCards(hand);
  const ranks = Object.keys(counts).map(Number).sort((a, b) => a - b);
  const parts = [];
  for (const rank of ranks) {
    const name = CARD_NAMES[rank];
    const cnt = counts[rank];
    if (rank === 13) {
      parts.push(`  ${C.MAGENTA}★조커${C.RESET}  × ${cnt}`);
    } else {
      parts.push(`  [${String(rank).padStart(2)}] ${name.padEnd(5)} × ${cnt}`);
    }
  }
  return parts.join("\n");
}

/** 순위에 따른 칭호 */
function getTitle(position, total) {
  if (position === 0) return "대달무티 👑";
  if (position === 1) return "달무티";
  if (position === total - 1) return "대빈민 💀";
  if (position === total - 2) return "빈민";
  return "시민";
}

/** 카드 이름 짧은 표기 */
function cardStr(rank) {
  return rank === 13 ? "★" : String(rank);
}

/** 이 PC의 LAN IPv4 주소 목록 (다른 PC에서 접속할 때 안내용) */
function getLocalIPs() {
  const nets = os.networkInterfaces();
  const ips = [];
  for (const name of Object.keys(nets)) {
    for (const netIf of nets[name] || []) {
      if (netIf.family === "IPv4" && !netIf.internal) {
        ips.push(netIf.address);
      }
    }
  }
  return ips;
}

// ════════════════════════════════════════
// 입출력 채널 (로컬 콘솔 / 네트워크 소켓)
// ════════════════════════════════════════

/** 호스트 자신의 로컬 콘솔을 감싸는 IO. 기존 ask()/console.log와 동일하게 동작 */
class LocalIO {
  write(text) {
    process.stdout.write(text);
  }
  question(prompt) {
    return ask(prompt);
  }
}
const localIO = new LocalIO();

/** 원격 플레이어(다른 PC)의 소켓을 감싸는 IO. 줄바꿈 단위로 입력을 처리 */
class SocketIO {
  constructor(socket, name) {
    this.socket = socket;
    this.name = name;
    this.isSocket = true;
    this.connected = true;
    this._buf = "";
    this._waiters = [];

    socket.on("data", (chunk) => this._onData(chunk));
    socket.on("close", () => this._onClose());
    socket.on("error", () => {});
  }

  _onData(chunk) {
    this._buf += chunk.toString("utf8");
    let idx;
    while ((idx = this._buf.indexOf("\n")) >= 0) {
      const raw = this._buf.slice(0, idx);
      this._buf = this._buf.slice(idx + 1);
      const line = raw.replace(/\r$/, "").trim();
      if (this._waiters.length > 0) {
        this._waiters.shift()(line);
      }
    }
  }

  _onClose() {
    this.connected = false;
    while (this._waiters.length > 0) {
      this._waiters.shift()("");
    }
  }

  write(text) {
    if (this.connected) {
      try {
        this.socket.write(text);
      } catch (e) {
        // 연결이 끊긴 경우 무시
      }
    }
  }

  question(prompt) {
    if (!this.connected) return Promise.resolve("");
    this.write(prompt);
    return new Promise((resolve) => this._waiters.push(resolve));
  }
}

/** 소켓에 연결되면 첫 줄(이름)을 읽어 반환. 이후 남은 데이터는 그대로 넘겨줌 */
function readFirstLine(socket) {
  return new Promise((resolve) => {
    let buf = "";
    function onData(chunk) {
      buf += chunk.toString("utf8");
      const idx = buf.indexOf("\n");
      if (idx >= 0) {
        socket.removeListener("data", onData);
        const line = buf.slice(0, idx).replace(/\r$/, "").trim();
        const rest = buf.slice(idx + 1);
        resolve({ line, rest });
      }
    }
    socket.on("data", onData);
    socket.on("close", () => {
      socket.removeListener("data", onData);
      resolve({ line: "", rest: "" });
    });
  });
}

// ════════════════════════════════════════
// 플레이어
// ════════════════════════════════════════

class Player {
  constructor(name, isHuman = true, io = null) {
    this.name = name;
    this.isHuman = isHuman;
    this.io = io;
    this.hand = [];
    this.finished = false;
    this.finishOrder = -1;
  }

  hasCards() {
    return this.hand.length > 0;
  }

  sortHand() {
    this.hand.sort((a, b) => a - b);
  }

  counts() {
    return countCards(this.hand);
  }

  /** 카드 제거: rank 카드 (count - jokerCount)장 + 조커 jokerCount장 */
  removeCards(rank, count, jokerCount = 0) {
    const normalCount = count - jokerCount;
    for (let i = 0; i < normalCount; i++) {
      const idx = this.hand.indexOf(rank);
      if (idx !== -1) this.hand.splice(idx, 1);
    }
    for (let i = 0; i < jokerCount; i++) {
      const idx = this.hand.indexOf(13);
      if (idx !== -1) this.hand.splice(idx, 1);
    }
  }

  /** 해당 조건으로 낼 수 있는 플레이 목록 반환 */
  getValidPlays(requiredCount, maxRank) {
    const c = this.counts();
    const jokers = c[13] || 0;
    const plays = [];

    for (let rank = 1; rank < maxRank; rank++) {
      const available = c[rank] || 0;
      if (available >= requiredCount) {
        plays.push({ rank, count: requiredCount, jokerCount: 0 });
      } else if (available > 0 && available + jokers >= requiredCount) {
        plays.push({ rank, count: requiredCount, jokerCount: requiredCount - available });
      }
    }
    return plays;
  }

  /** 낼 수 있는 카드가 있는지 */
  canPlay(requiredCount, maxRank) {
    return this.getValidPlays(requiredCount, maxRank).length > 0;
  }
}

class AIPlayer extends Player {
  constructor(name) {
    super(name, false);
  }

  /** AI 선 플레이: 가장 약한(높은 숫자) 카드부터 정리 */
  chooseLead() {
    const c = this.counts();
    const jokers = c[13] || 0;

    // 높은 숫자(약한 카드)부터 전부 내기
    for (let rank = 12; rank >= 1; rank--) {
      const available = c[rank] || 0;
      if (available > 0) {
        return { rank, count: available, jokerCount: 0 };
      }
    }

    // 조커만 남은 경우
    if (jokers > 0) {
      return { rank: 12, count: jokers, jokerCount: jokers };
    }
    return null;
  }

  /** AI 따라가기: 가장 약한 유효 카드로 이기기 (강한 카드 아끼기) */
  chooseFollow(currentRank, currentCount) {
    const plays = this.getValidPlays(currentCount, currentRank);
    if (plays.length === 0) return null;

    // 가장 높은 랭크(약한 카드) 우선, 조커 사용 최소화
    plays.sort((a, b) => {
      if (b.rank !== a.rank) return b.rank - a.rank;
      return a.jokerCount - b.jokerCount;
    });

    return plays[0];
  }
}

// ════════════════════════════════════════
// 게임
// ════════════════════════════════════════

class DalmutiGame {
  constructor() {
    this.players = [];
    this.roundNum = 0;
    this.rankings = []; // 이전 라운드 순위 (플레이어 인덱스 배열)
    this.scores = {};   // 누적 점수
    this.finishedPlayers = [];
    this.networkMode = false;
    this.server = null;
  }

  // ──── 방송(broadcast) 헬퍼: 접속한 모든 플레이어(로컬+원격)에게 동일 문구 전송 ────
  // 로컬 전용 모드에서는 모든 사람 플레이어가 같은 localIO를 공유하므로 자동으로 1회만 출력됨

  broadcast(text) {
    const targets = new Set(this.players.filter((p) => p.io).map((p) => p.io));
    for (const io of targets) io.write(text + "\n");
  }

  broadcastClear() {
    const targets = new Set(this.players.filter((p) => p.io).map((p) => p.io));
    for (const io of targets) io.write(CLEAR_CODE);
  }

  // ──── 설정 ────

  async setup() {
    clear();
    console.log(`${C.BOLD}${C.CYAN}`);
    console.log("╔═══════════════════════════════════════╗");
    console.log("║                                       ║");
    console.log("║     🎴  달 무 티  (Dalmuti)  🎴      ║");
    console.log("║                                       ║");
    console.log("║    카드를 가장 먼저 내려놓는 자가      ║");
    console.log("║          대달무티가 되리라!            ║");
    console.log("║                                       ║");
    console.log("╚═══════════════════════════════════════╝");
    console.log(`${C.RESET}\n`);

    // 게임 모드
    console.log(`${C.YELLOW}[게임 모드 선택]${C.RESET}`);
    console.log("  1. 혼자 vs AI");
    console.log("  2. 로컬 멀티플레이 (한 PC에서 여러 명)");
    console.log("  3. 혼합 (사람 + AI)");
    console.log("  4. 네트워크 호스트 (같은 Wi-Fi/공유기에서 각자 PC로 접속)\n");

    let mode;
    while (true) {
      mode = await ask("  모드 선택 (1-4): ");
      if (["1", "2", "3", "4"].includes(mode)) break;
      console.log("  1, 2, 3, 4 중 선택해주세요.");
    }

    // 인원 수
    let total;
    while (true) {
      const inp = await ask("\n  총 플레이어 수 (4-8): ");
      total = parseInt(inp);
      if (total >= 4 && total <= 8) break;
      console.log("  4~8명 사이로 입력해주세요.");
    }

    if (mode === "1") {
      const name = (await ask("  당신의 이름: ")) || "플레이어";
      this.players.push(new Player(name, true, localIO));
      for (let i = 0; i < total - 1; i++) {
        this.players.push(new AIPlayer(`AI-${i + 1}`));
      }
    } else if (mode === "2") {
      for (let i = 0; i < total; i++) {
        const name = (await ask(`  플레이어 ${i + 1} 이름: `)) || `플레이어${i + 1}`;
        this.players.push(new Player(name, true, localIO));
      }
    } else if (mode === "3") {
      let humans;
      while (true) {
        const inp = await ask(`\n  사람 플레이어 수 (1-${total - 1}): `);
        humans = parseInt(inp);
        if (humans >= 1 && humans < total) break;
        console.log(`  1~${total - 1}명 사이로 입력해주세요.`);
      }
      for (let i = 0; i < humans; i++) {
        const name = (await ask(`  플레이어 ${i + 1} 이름: `)) || `플레이어${i + 1}`;
        this.players.push(new Player(name, true, localIO));
      }
      for (let i = 0; i < total - humans; i++) {
        this.players.push(new AIPlayer(`AI-${i + 1}`));
      }
    } else {
      await this.setupNetworkHost(total);
    }

    for (const p of this.players) {
      this.scores[p.name] = 0;
    }

    this.broadcast(`\n  ${C.GREEN}게임 준비 완료! ${total}명으로 시작합니다.${C.RESET}`);
    await ask("\n  [Enter] 키를 눌러 시작...");
  }

  /** 네트워크 호스트 설정: TCP 서버를 열고 다른 PC들의 접속을 기다림 */
  async setupNetworkHost(total) {
    this.networkMode = true;

    const hostName = (await ask("  당신(호스트)의 이름: ")) || "호스트";
    this.players.push(new Player(hostName, true, localIO));

    // 원격 인원 수를 미리 정하지 않음 - 접속한 사람 수만큼만 사람, 나머지는 AI로 자동 채움
    const maxRemote = total - 1;

    let port;
    while (true) {
      const inp = await ask(`  포트 번호 (기본 ${DEFAULT_PORT}): `);
      port = inp ? parseInt(inp) : DEFAULT_PORT;
      if (!isNaN(port) && port > 0 && port < 65536) break;
      console.log("  올바른 포트 번호를 입력해주세요.");
    }

    const ips = getLocalIPs();
    console.log(`\n  ${C.YELLOW}다른 플레이어는 같은 Wi-Fi/네트워크에서 아래 주소로 접속하세요:${C.RESET}`);
    if (ips.length > 0) {
      for (const ip of ips) console.log(`    ${C.GREEN}${ip}:${port}${C.RESET}`);
    } else {
      console.log(`    ${C.DIM}(로컬 IP를 찾을 수 없습니다. ipconfig/ifconfig로 직접 확인하세요)${C.RESET}`);
    }
    console.log(`  다른 PC에서 ${C.WHITE}node dalmuti.js${C.RESET} 실행 → 메뉴 "2. 네트워크 게임 참가" → 위 주소 입력\n`);

    const server = net.createServer();
    this.server = server;
    const connected = [];

    const printWaitingStatus = () => {
      const aiIfStartNow = maxRemote - connected.length;
      console.log(
        `  ${C.GREEN}현재 접속: ${connected.length}/${maxRemote}명${C.RESET}` +
          `  ${C.DIM}(지금 시작하면 AI ${aiIfStartNow}명이 빈 자리를 채웁니다)${C.RESET}`
      );
    };

    await new Promise((resolve, reject) => {
      server.once("error", (err) => {
        console.log(`  ${C.RED}서버 오류: ${err.message}${C.RESET}`);
        reject(err);
      });
      server.listen(port, () => {
        console.log(`  ${C.GREEN}서버가 포트 ${port}에서 대기 중입니다...${C.RESET}`);
        console.log(`  ${C.YELLOW}사람이 최대 ${maxRemote}명까지 참여할 수 있습니다.${C.RESET}`);
        console.log(`  ${C.YELLOW}[Enter]를 누르면 지금까지 접속한 사람 + AI로 바로 시작합니다.${C.RESET}\n`);
        resolve();
      });
    });

    server.on("connection", async (socket) => {
      socket.on("error", () => {});
      const { line, rest } = await readFirstLine(socket);
      if (connected.length >= maxRemote) {
        // 이미 정원이 찼으면 정중히 거절
        socket.write(`${C.RED}이미 정원이 다 찼습니다. 연결을 종료합니다.${C.RESET}\n`);
        socket.end();
        return;
      }
      const name = line || `플레이어${connected.length + 1}`;
      const io = new SocketIO(socket, name);
      if (rest) io._onData(Buffer.from(rest, "utf8"));
      connected.push({ name, io });
      io.write(`${C.GREEN}접속 완료! 호스트가 게임을 시작하기를 기다리는 중...${C.RESET}\n`);
      console.log(`  ${C.GREEN}✔ ${name} 님이 참여했습니다.${C.RESET}`);
      printWaitingStatus();
    });

    // 정원이 다 찼거나, 호스트가 [Enter]를 누르면 대기 종료 (남은 자리는 AI로 채움)
    await new Promise((resolve) => {
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        rl.removeListener("line", onEnter);
        resolve();
      };
      const onEnter = () => finish();
      rl.once("line", onEnter);

      (async () => {
        while (!done && connected.length < maxRemote) {
          await sleep(300);
        }
        finish();
      })();
    });

    server.close(); // 이후 새 접속은 받지 않음 (이미 연결된 소켓은 유지)

    for (const c of connected) {
      this.players.push(new Player(c.name, true, c.io));
    }

    const aiCount = total - this.players.length;
    for (let i = 0; i < aiCount; i++) {
      this.players.push(new AIPlayer(`AI-${i + 1}`));
    }

    console.log(`\n  ${C.GREEN}사람 ${connected.length}명 + AI ${aiCount}명으로 시작합니다.${C.RESET}`);
  }

  // ──── 카드 배분 ────

  dealCards() {
    const deck = shuffle(createDeck());

    for (const p of this.players) {
      p.hand = [];
      p.finished = false;
      p.finishOrder = -1;
    }
    this.finishedPlayers = [];

    for (let i = 0; i < deck.length; i++) {
      this.players[i % this.players.length].hand.push(deck[i]);
    }
    for (const p of this.players) {
      p.sortHand();
    }
  }

  // ──── 다음 활성 플레이어 ────

  nextActive(idx) {
    const n = this.players.length;
    let next = (idx + 1) % n;
    let attempts = 0;
    while (this.players[next].finished && attempts < n) {
      next = (next + 1) % n;
      attempts++;
    }
    return next;
  }

  // ──── 게임 상태 표시 (로컬: 공유 화면 1개) ────

  displayState(currentIdx, tableRank = null, tableCount = null, tablePlayer = null) {
    clear();
    const cp = this.players[currentIdx];
    const n = this.players.length;

    console.log(`${C.BOLD}${C.CYAN}╔══════════════════════════════════════════════╗`);
    console.log(`║  🎴 달무티 - 라운드 ${String(this.roundNum).padEnd(3)}                    ║`);
    console.log(`╠══════════════════════════════════════════════╣${C.RESET}`);

    for (let i = 0; i < n; i++) {
      const p = this.players[i];
      const marker = i === currentIdx ? ` ${C.YELLOW}◀${C.RESET}` : "";
      let status;
      if (p.finished) {
        status = `✅ ${getTitle(p.finishOrder, n)}`;
      } else {
        status = `카드 ${String(p.hand.length).padStart(2)}장`;
      }

      let prevTitle = "";
      if (this.roundNum > 1 && this.rankings.length > 0) {
        const prevPos = this.rankings.indexOf(i);
        if (prevPos >= 0) {
          prevTitle = `${C.DIM}(${getTitle(prevPos, n)})${C.RESET}`;
        }
      }

      console.log(`  ${p.name.padEnd(12)} ${status.padEnd(22)} ${prevTitle}${marker}`);
    }

    console.log(`${C.CYAN}╠══════════════════════════════════════════════╣${C.RESET}`);

    if (tableRank !== null) {
      console.log(`  바닥: [${cardStr(tableRank)}] ${CARD_NAMES[tableRank]} × ${tableCount}장  (${tablePlayer})`);
    } else {
      console.log(`  바닥: ${C.DIM}(비어있음 - 선)${C.RESET}`);
    }

    console.log(`${C.CYAN}╠══════════════════════════════════════════════╣${C.RESET}`);

    if (cp.isHuman && !cp.finished) {
      console.log(`  ${C.GREEN}${cp.name}의 패:${C.RESET}`);
      console.log(handSummary(cp.hand));
    } else if (!cp.finished) {
      console.log(`  ${cp.name}(AI)의 차례...`);
    }

    console.log(`${C.CYAN}╚══════════════════════════════════════════════╝${C.RESET}\n`);
  }

  // ──── 게임 상태 표시 (네트워크: 각자 화면에 자기 패를 항상 표시) ────

  broadcastState(currentIdx, tableRank = null, tableCount = null, tablePlayer = null) {
    const n = this.players.length;
    const lines = [];

    lines.push(`${C.BOLD}${C.CYAN}╔══════════════════════════════════════════════╗`);
    lines.push(`║  🎴 달무티 - 라운드 ${String(this.roundNum).padEnd(3)}                    ║`);
    lines.push(`╠══════════════════════════════════════════════╣${C.RESET}`);

    for (let i = 0; i < n; i++) {
      const p = this.players[i];
      const marker = i === currentIdx ? ` ${C.YELLOW}◀${C.RESET}` : "";
      let status;
      if (p.finished) {
        status = `✅ ${getTitle(p.finishOrder, n)}`;
      } else {
        status = `카드 ${String(p.hand.length).padStart(2)}장`;
      }

      let prevTitle = "";
      if (this.roundNum > 1 && this.rankings.length > 0) {
        const prevPos = this.rankings.indexOf(i);
        if (prevPos >= 0) {
          prevTitle = `${C.DIM}(${getTitle(prevPos, n)})${C.RESET}`;
        }
      }

      lines.push(`  ${p.name.padEnd(12)} ${status.padEnd(22)} ${prevTitle}${marker}`);
    }

    lines.push(`${C.CYAN}╠══════════════════════════════════════════════╣${C.RESET}`);

    if (tableRank !== null) {
      lines.push(`  바닥: [${cardStr(tableRank)}] ${CARD_NAMES[tableRank]} × ${tableCount}장  (${tablePlayer})`);
    } else {
      lines.push(`  바닥: ${C.DIM}(비어있음 - 선)${C.RESET}`);
    }

    lines.push(`${C.CYAN}╠══════════════════════════════════════════════╣${C.RESET}`);
    const common = lines.join("\n");

    for (let i = 0; i < n; i++) {
      const p = this.players[i];
      if (!p.io) continue; // AI는 화면 없음

      let body = CLEAR_CODE + common + "\n";
      if (p.finished) {
        body += `  ${C.DIM}완료했습니다. 다른 플레이어를 기다리는 중...${C.RESET}\n`;
      } else if (i === currentIdx) {
        body += `  ${C.YELLOW}▶ 당신의 차례입니다!${C.RESET}\n`;
      } else {
        body += `  ${C.DIM}${this.players[currentIdx].name}의 차례...${C.RESET}\n`;
      }
      if (!p.finished) {
        body += `  ${C.GREEN}내 패:${C.RESET}\n${handSummary(p.hand)}\n`;
      }
      body += `${C.CYAN}╚══════════════════════════════════════════════╝${C.RESET}\n`;
      p.io.write(body);
    }
  }

  showState(currentIdx, tableRank = null, tableCount = null, tablePlayer = null) {
    if (this.networkMode) {
      this.broadcastState(currentIdx, tableRank, tableCount, tablePlayer);
    } else {
      this.displayState(currentIdx, tableRank, tableCount, tablePlayer);
    }
  }

  // ──── 카드 교환 ────

  async cardExchange() {
    const n = this.players.length;
    if (n < 4 || this.rankings.length === 0) return;

    const greatDalmuti = this.players[this.rankings[0]];
    const dalmuti = this.players[this.rankings[1]];
    const peon = this.players[this.rankings[n - 2]];
    const greatPeon = this.players[this.rankings[n - 1]];

    // 혁명 체크
    const jokerCount = greatPeon.hand.filter((c) => c === 13).length;
    if (jokerCount === 2) {
      this.broadcastClear();
      this.broadcast(`\n${C.RED}${"═".repeat(44)}`);
      this.broadcast(`  🔥 혁명! ${greatPeon.name}이(가) 조커 2장 보유!`);
      this.broadcast(`  카드 교환이 취소됩니다!`);
      this.broadcast(`${"═".repeat(44)}${C.RESET}`);
      await ask("\n  [Enter] 계속...");
      return;
    }

    this.broadcastClear();
    this.broadcast(`\n${C.YELLOW}${"═".repeat(44)}`);
    this.broadcast(`  📜 카드 교환`);
    this.broadcast(`${"═".repeat(44)}${C.RESET}\n`);

    // 대빈민 → 대달무티: 최고 카드 2장 (가장 낮은 숫자)
    greatPeon.sortHand();
    const bestCards = [];
    for (const card of [...greatPeon.hand]) {
      if (card !== 13 && bestCards.length < 2) bestCards.push(card);
    }
    while (bestCards.length < 2 && greatPeon.hand.includes(13)) {
      bestCards.push(13);
    }

    for (const card of bestCards) {
      const idx = greatPeon.hand.indexOf(card);
      if (idx !== -1) {
        greatPeon.hand.splice(idx, 1);
        greatDalmuti.hand.push(card);
      }
    }
    this.broadcast(`  ${greatPeon.name}(대빈민) → ${greatDalmuti.name}(대달무티): [${bestCards.join(", ")}]`);

    // 대달무티 → 대빈민: 아무 카드 2장
    await this.giveCards(greatDalmuti, greatPeon, 2);

    // 빈민 → 달무티: 최고 카드 1장
    peon.sortHand();
    let bestCard = peon.hand.find((c) => c !== 13);
    if (bestCard === undefined && peon.hand.length > 0) bestCard = peon.hand[0];

    if (bestCard !== undefined) {
      const idx = peon.hand.indexOf(bestCard);
      peon.hand.splice(idx, 1);
      dalmuti.hand.push(bestCard);
      this.broadcast(`  ${peon.name}(빈민) → ${dalmuti.name}(달무티): [${bestCard}]`);
    }

    // 달무티 → 빈민: 아무 카드 1장
    await this.giveCards(dalmuti, peon, 1);

    for (const p of this.players) p.sortHand();
    await ask("\n  [Enter] 계속...");
  }

  async giveCards(giver, receiver, count) {
    const disconnected = giver.isHuman && giver.io && giver.io.connected === false;

    if (giver.isHuman && !disconnected) {
      giver.sortHand();
      giver.io.write(`\n  ${giver.name}님, ${receiver.name}에게 줄 카드 ${count}장을 선택하세요:\n`);
      giver.io.write(`  현재 패:\n${handSummary(giver.hand)}\n\n`);

      const given = [];
      for (let i = 0; i < count; i++) {
        while (true) {
          if (giver.io.connected === false) break;
          const inp = await giver.io.question(`  줄 카드 번호 (${i + 1}/${count}): `);
          const rank = parseInt(inp);
          const idx = giver.hand.indexOf(rank);
          if (idx !== -1) {
            giver.hand.splice(idx, 1);
            receiver.hand.push(rank);
            given.push(rank);
            break;
          } else {
            giver.io.write(`  ${C.RED}해당 카드가 패에 없습니다.${C.RESET}\n`);
          }
        }
      }
      this.broadcast(`  ${giver.name} → ${receiver.name}: [${given.join(", ")}]`);
    } else {
      // AI (또는 연결이 끊긴 플레이어): 가장 높은 숫자(약한 카드)를 줌, 조커는 보존
      giver.sortHand();
      const given = [];
      for (let i = 0; i < count; i++) {
        if (giver.hand.length > 0) {
          // 조커가 아닌 가장 높은 숫자
          let cardIdx = -1;
          for (let j = giver.hand.length - 1; j >= 0; j--) {
            if (giver.hand[j] !== 13) {
              cardIdx = j;
              break;
            }
          }
          if (cardIdx === -1) cardIdx = giver.hand.length - 1; // 조커밖에 없으면 조커
          const card = giver.hand[cardIdx];
          giver.hand.splice(cardIdx, 1);
          receiver.hand.push(card);
          given.push(card);
        }
      }
      this.broadcast(`  ${giver.name} → ${receiver.name}: [${given.join(", ")}]`);
    }
  }

  // ──── 사람 입력 ────

  async humanChooseLead(player) {
    const c = player.counts();

    while (true) {
      if (player.io.connected === false) {
        return AIPlayer.prototype.chooseLead.call(player);
      }
      player.io.write(`  ${C.YELLOW}선으로 카드를 내세요.${C.RESET}\n`);
      player.io.write(`  형식: ${C.WHITE}카드번호 장수${C.RESET}  (예: ${C.GREEN}5 3${C.RESET} = 5를 3장)\n`);
      player.io.write(`  조커: ${C.WHITE}카드번호 장수 조커수${C.RESET}  (예: ${C.GREEN}5 3 1${C.RESET} = 5를 3장, 조커1)\n`);

      const inp = await player.io.question(`\n  > `);
      const parts = inp.split(/\s+/);

      if (parts.length < 1 || !parts[0]) continue;

      const rank = parseInt(parts[0]);
      if (isNaN(rank) || rank < 1 || rank > 12) {
        player.io.write(`  ${C.RED}1~12 사이의 숫자를 입력하세요.${C.RESET}\n`);
        continue;
      }

      const available = c[rank] || 0;
      const jokersAvail = c[13] || 0;

      let count, jokerCount;

      if (parts.length >= 2) {
        count = parseInt(parts[1]);
      } else {
        count = available;
        const confirm = await player.io.question(`  → ${count}장 전부 내시겠습니까? (y/장수): `);
        if (confirm && confirm !== "y") {
          count = parseInt(confirm);
          if (isNaN(count)) continue;
        }
      }

      jokerCount = parts.length >= 3 ? parseInt(parts[2]) : 0;
      if (isNaN(count) || isNaN(jokerCount)) {
        player.io.write(`  ${C.RED}숫자를 올바르게 입력해주세요.${C.RESET}\n`);
        continue;
      }

      const normalNeeded = count - jokerCount;

      if (count < 1) {
        player.io.write(`  ${C.RED}1장 이상 내야 합니다.${C.RESET}\n`);
        continue;
      }
      if (normalNeeded < 0) {
        player.io.write(`  ${C.RED}조커 수가 총 장수보다 많습니다.${C.RESET}\n`);
        continue;
      }
      if (normalNeeded > available) {
        player.io.write(`  ${C.RED}[${rank}] 카드가 ${available}장밖에 없습니다.${C.RESET}\n`);
        continue;
      }
      if (jokerCount > jokersAvail) {
        player.io.write(`  ${C.RED}조커가 ${jokersAvail}장밖에 없습니다.${C.RESET}\n`);
        continue;
      }

      return { rank, count, jokerCount };
    }
  }

  async humanChooseFollow(player, reqRank, reqCount) {
    if (!player.canPlay(reqCount, reqRank)) {
      player.io.write(`  ${C.DIM}낼 수 있는 카드가 없습니다. 자동 패스!${C.RESET}\n`);
      await sleep(1000);
      return null;
    }

    while (true) {
      if (player.io.connected === false) {
        return null;
      }
      player.io.write(`  ${C.YELLOW}[${reqRank}]보다 낮은 숫자로 ${reqCount}장을 내세요. (패스: p)${C.RESET}\n`);

      const inp = await player.io.question(`  > `);

      if (inp.toLowerCase() === "p") return null;

      const parts = inp.split(/\s+/);
      if (parts.length < 1) continue;

      const rank = parseInt(parts[0]);
      const count = parts.length >= 2 ? parseInt(parts[1]) : reqCount;
      const jokerCount = parts.length >= 3 ? parseInt(parts[2]) : 0;

      if (isNaN(rank) || isNaN(count) || isNaN(jokerCount)) {
        player.io.write(`  ${C.RED}올바른 형식으로 입력해주세요. 예: '3 2' 또는 'p'${C.RESET}\n`);
        continue;
      }

      const c = player.counts();
      const available = c[rank] || 0;
      const jokersAvail = c[13] || 0;
      const normalNeeded = count - jokerCount;

      if (rank < 1 || rank > 12) {
        player.io.write(`  ${C.RED}1~12 사이의 숫자를 입력하세요.${C.RESET}\n`);
        continue;
      }
      if (rank >= reqRank) {
        player.io.write(`  ${C.RED}${reqRank}보다 작은 숫자를 내야 합니다.${C.RESET}\n`);
        continue;
      }
      if (count !== reqCount) {
        player.io.write(`  ${C.RED}정확히 ${reqCount}장을 내야 합니다.${C.RESET}\n`);
        continue;
      }
      if (normalNeeded < 0) {
        player.io.write(`  ${C.RED}조커 수가 총 장수보다 많습니다.${C.RESET}\n`);
        continue;
      }
      if (normalNeeded > available) {
        player.io.write(`  ${C.RED}[${rank}] 카드가 ${available}장밖에 없습니다.${C.RESET}\n`);
        continue;
      }
      if (jokerCount > jokersAvail) {
        player.io.write(`  ${C.RED}조커가 ${jokersAvail}장밖에 없습니다.${C.RESET}\n`);
        continue;
      }

      return { rank, count, jokerCount };
    }
  }

  // ──── 트릭 ────

  async playTrick(leaderIdx) {
    const leader = this.players[leaderIdx];
    const n = this.players.length;

    // ── 리더 플레이 ──
    this.showState(leaderIdx);

    // 로컬 멀티: 패 가리기 (네트워크 모드는 각자 화면이 이미 분리되어 있으므로 불필요)
    const humanCount = this.players.filter((p) => p.isHuman && !p.finished).length;
    if (!this.networkMode && leader.isHuman && humanCount > 1) {
      await ask(`  ${leader.name}님 차례입니다. [Enter]를 눌러 패를 확인하세요...`);
      this.displayState(leaderIdx);
    }

    let play;
    const leaderDisconnected = leader.isHuman && leader.io && leader.io.connected === false;
    if (leader.isHuman && !leaderDisconnected) {
      play = await this.humanChooseLead(leader);
    } else {
      play = leader.chooseLead ? leader.chooseLead() : AIPlayer.prototype.chooseLead.call(leader);
      if (!play) play = { rank: 1, count: leader.hand.filter((c) => c === 13).length, jokerCount: leader.hand.filter((c) => c === 13).length };
      await sleep(800);
    }

    leader.removeCards(play.rank, play.count, play.jokerCount);

    const jokerStr = play.jokerCount > 0 ? ` (조커 ${play.jokerCount}장 포함)` : "";
    this.broadcast(`  → ${leader.name}: [${play.rank}] ${CARD_NAMES[play.rank]} × ${play.count}장${jokerStr}`);

    let currentRank = play.rank;
    let currentCount = play.count;
    let trickWinnerIdx = leaderIdx;

    // 리더가 카드를 다 냈는지
    if (!leader.hasCards()) {
      leader.finished = true;
      leader.finishOrder = this.finishedPlayers.length;
      this.finishedPlayers.push(leaderIdx);
      this.broadcast(`  🎉 ${leader.name} 완료! → ${getTitle(leader.finishOrder, n)}`);
      await sleep(1000);
    }

    // ── 나머지 순환 ──
    const passedPlayers = new Set();
    let currentIdx = this.nextActive(leaderIdx);

    while (true) {
      // 활성 플레이어 확인
      const activeIndices = [];
      for (let i = 0; i < n; i++) {
        if (!this.players[i].finished) activeIndices.push(i);
      }

      if (activeIndices.length <= 1) break;

      // 트릭 위너에게 돌아왔으면 (위너가 아직 활성인 경우)
      if (currentIdx === trickWinnerIdx && !this.players[trickWinnerIdx].finished) {
        break;
      }

      // 트릭 위너가 끝났는데, 남은 모든 활성 플레이어가 패스했으면
      if (this.players[trickWinnerIdx].finished) {
        const nonWinnerActive = activeIndices.filter((i) => i !== trickWinnerIdx);
        if (nonWinnerActive.every((i) => passedPlayers.has(i))) break;
      }

      const player = this.players[currentIdx];

      this.showState(currentIdx, currentRank, currentCount, this.players[trickWinnerIdx].name);

      if (!this.networkMode && player.isHuman && humanCount > 1) {
        await ask(`  ${player.name}님 차례입니다. [Enter]를 눌러 패를 확인하세요...`);
        this.displayState(currentIdx, currentRank, currentCount, this.players[trickWinnerIdx].name);
      }

      let result;
      const playerDisconnected = player.isHuman && player.io && player.io.connected === false;
      if (player.isHuman && !playerDisconnected) {
        result = await this.humanChooseFollow(player, currentRank, currentCount);
      } else {
        result = player.chooseFollow
          ? player.chooseFollow(currentRank, currentCount)
          : AIPlayer.prototype.chooseFollow.call(player, currentRank, currentCount);
        await sleep(800);
      }

      if (result === null) {
        this.broadcast(`  → ${player.name}: 패스 ✋`);
        passedPlayers.add(currentIdx);
        await sleep(500);
      } else {
        player.removeCards(result.rank, result.count, result.jokerCount);

        const jStr = result.jokerCount > 0 ? ` (조커 ${result.jokerCount}장 포함)` : "";
        this.broadcast(`  → ${player.name}: [${result.rank}] ${CARD_NAMES[result.rank]} × ${result.count}장${jStr}`);

        currentRank = result.rank;
        trickWinnerIdx = currentIdx;
        passedPlayers.clear();

        if (!player.hasCards()) {
          player.finished = true;
          player.finishOrder = this.finishedPlayers.length;
          this.finishedPlayers.push(currentIdx);
          this.broadcast(`  🎉 ${player.name} 완료! → ${getTitle(player.finishOrder, n)}`);
          await sleep(1000);
        }

        await sleep(500);
      }

      currentIdx = this.nextActive(currentIdx);
    }

    // 트릭 종료
    const activeLeft = this.players.filter((p) => !p.finished);
    if (activeLeft.length > 1) {
      if (!this.players[trickWinnerIdx].finished) {
        this.broadcast(`\n  ${C.GREEN}>>> ${this.players[trickWinnerIdx].name}이(가) 트릭 승리!${C.RESET}`);
      }
    }

    await ask("  [Enter] 계속...");

    // 다음 리더 결정
    if (!this.players[trickWinnerIdx].finished) {
      return trickWinnerIdx;
    } else {
      return this.nextActive(trickWinnerIdx);
    }
  }

  // ──── 라운드 ────

  async playRound() {
    this.roundNum++;
    this.dealCards();

    // 카드 교환 (2라운드부터)
    if (this.roundNum > 1 && this.rankings.length > 0) {
      await this.cardExchange();
    }

    // 시작 플레이어
    let leaderIdx;
    if (this.roundNum === 1) {
      leaderIdx = this.players.findIndex((p) => p.hand.includes(1));
      if (leaderIdx === -1) leaderIdx = 0;
    } else {
      leaderIdx = this.rankings[0];
    }

    this.finishedPlayers = [];

    this.broadcastClear();
    this.broadcast(`\n  ${C.BOLD}라운드 ${this.roundNum} 시작!${C.RESET}`);
    if (this.roundNum === 1) {
      this.broadcast(`  ${this.players[leaderIdx].name}이(가) [1] 달무티 카드를 갖고 있어 선으로 시작!`);
    } else {
      this.broadcast(`  ${this.players[leaderIdx].name}(대달무티)이(가) 선으로 시작!`);
    }
    await ask("  [Enter] 계속...");

    // 트릭 반복
    while (true) {
      const remaining = this.players
        .map((p, i) => ({ p, i }))
        .filter(({ p }) => !p.finished);

      if (remaining.length <= 1) {
        if (remaining.length === 1) {
          const last = remaining[0];
          last.p.finished = true;
          last.p.finishOrder = this.finishedPlayers.length;
          this.finishedPlayers.push(last.i);
        }
        break;
      }

      // 리더가 끝났으면 다음 활성 플레이어
      while (this.players[leaderIdx].finished) {
        leaderIdx = this.nextActive(leaderIdx);
      }

      leaderIdx = await this.playTrick(leaderIdx);
    }

    this.rankings = [...this.finishedPlayers];
    await this.showRoundResults();
  }

  // ──── 결과 ────

  async showRoundResults() {
    this.broadcastClear();
    const n = this.players.length;

    this.broadcast(`\n${C.BOLD}${C.YELLOW}╔══════════════════════════════════════════════╗`);
    this.broadcast(`║           📊 라운드 ${String(this.roundNum).padEnd(3)} 결과               ║`);
    this.broadcast(`╠══════════════════════════════════════════════╣${C.RESET}`);

    for (let pos = 0; pos < this.rankings.length; pos++) {
      const pidx = this.rankings[pos];
      const p = this.players[pidx];
      const title = getTitle(pos, n);
      const points = n - pos;
      this.scores[p.name] = (this.scores[p.name] || 0) + points;
      this.broadcast(`  ${pos + 1}등  ${title.padEnd(15)} ${p.name.padEnd(12)} (+${points}점)`);
    }

    this.broadcast(`\n${C.CYAN}  --- 누적 점수 ---${C.RESET}`);
    const sorted = Object.entries(this.scores).sort((a, b) => b[1] - a[1]);
    for (const [name, score] of sorted) {
      this.broadcast(`  ${name.padEnd(15)} ${score}점`);
    }

    this.broadcast(`${C.YELLOW}╚══════════════════════════════════════════════╝${C.RESET}`);
  }

  // ──── 메인 루프 ────

  async run() {
    await this.setup();

    while (true) {
      await this.playRound();

      console.log();
      const again = await ask("  다음 라운드를 하시겠습니까? (y/n): ");
      if (again.toLowerCase() !== "y") break;
    }

    // 최종 결과
    this.broadcastClear();
    this.broadcast(`\n${C.BOLD}${C.CYAN}╔══════════════════════════════════════════════╗`);
    this.broadcast(`║              🏆 최종 결과 🏆                ║`);
    this.broadcast(`╠══════════════════════════════════════════════╣${C.RESET}`);

    const sorted = Object.entries(this.scores).sort((a, b) => b[1] - a[1]);
    const medals = ["🥇", "🥈", "🥉"];
    for (let i = 0; i < sorted.length; i++) {
      const [name, score] = sorted[i];
      const medal = i < 3 ? medals[i] : "  ";
      this.broadcast(`  ${medal} ${name.padEnd(15)} ${score}점`);
    }

    this.broadcast(`${C.CYAN}╚══════════════════════════════════════════════╝${C.RESET}`);
    this.broadcast(`\n  ${C.GREEN}게임을 플레이해주셔서 감사합니다! 🎴${C.RESET}\n`);

    if (this.networkMode) {
      for (const p of this.players) {
        if (p.io && p.io.isSocket) {
          try {
            p.io.socket.end();
          } catch (e) {
            // 무시
          }
        }
      }
    }
  }
}

// ════════════════════════════════════════
// 네트워크 클라이언트 (다른 PC에서 호스트에 접속)
// ════════════════════════════════════════

async function runNetworkClient() {
  clear();
  console.log(`${C.BOLD}${C.CYAN}[네트워크 게임 참가]${C.RESET}\n`);

  const host = await ask("  호스트 IP 주소: ");
  const portInp = await ask(`  포트 번호 (기본 ${DEFAULT_PORT}): `);
  const port = portInp ? parseInt(portInp) : DEFAULT_PORT;
  const name = (await ask("  당신의 이름: ")) || "플레이어";

  console.log(`\n  ${C.YELLOW}연결 중...${C.RESET}`);

  await new Promise((resolve) => {
    const socket = net.connect(port, host, () => {
      socket.write(name + "\n");
    });

    socket.on("error", (err) => {
      console.log(`  ${C.RED}연결 실패: ${err.message}${C.RESET}`);
      resolve();
    });

    socket.on("connect", () => {
      // 연결되면 이후로는 화면/키보드를 그대로 소켓과 주고받는 '단말기' 역할만 함
      rl.pause();
      process.stdin.setEncoding("utf8");
      process.stdin.pipe(socket);
      socket.pipe(process.stdout);

      socket.on("close", () => {
        console.log(`\n  ${C.DIM}서버와 연결이 종료되었습니다.${C.RESET}`);
        process.stdin.unpipe(socket);
        rl.resume();
        resolve();
      });
    });
  });
}

// ════════════════════════════════════════
// 규칙 보기
// ════════════════════════════════════════

async function showRules() {
  clear();
  console.log(`
${C.BOLD}${C.CYAN}📜 달무티 규칙${C.RESET}

${C.YELLOW}[카드 구성]${C.RESET}
  • 1(달무티) × 1장, 2(대주교) × 2장, ... 12(빈민) × 12장
  • 조커(★) × 2장 → 총 80장
  • ${C.RED}숫자가 낮을수록 강한 카드!${C.RESET}

${C.YELLOW}[게임 진행]${C.RESET}
  1. 모든 카드를 균등하게 나눕니다
  2. 선 플레이어가 같은 숫자 카드 N장을 냅니다
  3. 다음 플레이어는 더 ${C.RED}낮은 숫자${C.RESET}로 ${C.RED}같은 장수${C.RESET}를 내거나 패스합니다
  4. 모두 패스하면 마지막으로 낸 사람이 새로운 선
  5. 카드를 먼저 다 내면 높은 순위!

${C.YELLOW}[조커 ★]${C.RESET}
  • 아무 카드 대신 사용 가능 (와일드카드)
  • 다른 카드와 함께 사용 (예: 5를 3장 낼 때 조커 1장 + 5카드 2장)

${C.YELLOW}[계급 & 카드 교환]${C.RESET}
  • 1등 = 대달무티 👑, 꼴등 = 대빈민 💀
  • 다음 라운드 시작 전 교환:
    - 대빈민 → 대달무티: 최고 카드 2장 강제 헌납
    - 대달무티 → 대빈민: 아무 카드 2장 하사
    - 빈민 → 달무티: 최고 카드 1장
    - 달무티 → 빈민: 아무 카드 1장

${C.YELLOW}[혁명 🔥]${C.RESET}
  • 대빈민이 조커 2장을 모두 갖고 있으면 혁명!
  • 카드 교환이 취소됩니다

${C.YELLOW}[입력 방법]${C.RESET}
  • 카드 내기: ${C.WHITE}숫자 장수${C.RESET} (예: 5 3 = 5를 3장)
  • 조커 포함: ${C.WHITE}숫자 장수 조커수${C.RESET} (예: 5 3 1 = 5를 3장 중 조커1)
  • 패스:     ${C.WHITE}p${C.RESET}

${C.YELLOW}[네트워크 멀티플레이]${C.RESET}
  • 한 명이 "네트워크 호스트" 모드로 게임을 시작합니다 (같은 Wi-Fi/공유기 필요)
  • 호스트 화면에 표시되는 IP 주소:포트를 다른 플레이어들에게 알려줍니다
  • 다른 플레이어는 각자 자기 PC에서 게임을 실행하고
    메인 메뉴 "2. 네트워크 게임 참가"에서 그 주소로 접속하면 됩니다
  • 몇 명이 참여할지 미리 정할 필요 없음 - 사람들이 들어오는 대로 대기실에 표시되고,
    호스트가 [Enter]를 누르면 그 시점까지 접속한 사람 + 나머지는 AI로 채워서 바로 시작합니다
  • 접속 후에는 각자 자기 패만 자신의 화면에서 볼 수 있습니다
`);
  await ask("  [Enter] 돌아가기...");
}

// ════════════════════════════════════════
// 메인 메뉴
// ════════════════════════════════════════

async function main() {
  while (true) {
    clear();
    console.log(`
${C.BOLD}${C.CYAN}
  ╔═══════════════════════════════════════╗
  ║                                       ║
  ║     🎴  달 무 티  (Dalmuti)  🎴      ║
  ║                                       ║
  ║     The Great Dalmuti Card Game       ║
  ║                                       ║
  ╚═══════════════════════════════════════╝
${C.RESET}
  ${C.YELLOW}1.${C.RESET} 게임 시작 (혼자/로컬멀티/네트워크 호스트)
  ${C.YELLOW}2.${C.RESET} 네트워크 게임 참가 (다른 PC의 호스트에 접속)
  ${C.YELLOW}3.${C.RESET} 규칙 보기
  ${C.YELLOW}4.${C.RESET} 종료
`);

    const choice = await ask("  선택: ");

    if (choice === "1") {
      const game = new DalmutiGame();
      await game.run();
    } else if (choice === "2") {
      await runNetworkClient();
    } else if (choice === "3") {
      await showRules();
    } else if (choice === "4") {
      console.log(`\n  ${C.GREEN}안녕히 가세요! 🎴${C.RESET}\n`);
      rl.close();
      process.exit(0);
    } else {
      console.log("  1, 2, 3, 4 중 선택해주세요.");
      await sleep(1000);
    }
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error(err);
    rl.close();
    process.exit(1);
  });
}

// 다른 스크립트(예: 디스코드 봇)에서 카드 규칙 로직을 재사용할 수 있도록 export
module.exports = {
  CARD_NAMES,
  createDeck,
  shuffle,
  countCards,
  getTitle,
  cardStr,
  Player,
  AIPlayer,
};
