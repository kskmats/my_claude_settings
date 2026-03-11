#!/usr/bin/env node
// Claude Code custom status line
// stdin JSON + Anthropic Usage API + git info

const fs = require('fs');
const path = require('path');
const { execSync, spawn } = require('child_process');

const HOME = process.env.HOME || '';
const CACHE_DIR = path.join(HOME, '.claude', '.statusline-cache');
const USAGE_CACHE = path.join(CACHE_DIR, 'usage.json');
const USAGE_MAX_AGE = 180; // 3分

// ANSI
const R = '\x1b[0m';
const B = '\x1b[1m';
const D = '\x1b[2m';
const CYAN = '\x1b[36m';
const GREEN = '\x1b[32m';
const YELLOW = '\x1b[33m';
const RED = '\x1b[31m';
const BLUE = '\x1b[34m';
const MAG = '\x1b[35m';

function ensureCacheDir() {
  if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });
}

function readCache(file, maxAge) {
  try {
    const stat = fs.statSync(file);
    const age = (Date.now() - stat.mtimeMs) / 1000;
    if (age > maxAge) return null;
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch { return null; }
}

function writeCache(file, data) {
  try {
    ensureCacheDir();
    fs.writeFileSync(file, JSON.stringify(data));
  } catch {}
}

// macOSキーチェーンからOAuthトークンを取得
function getOAuthToken() {
  try {
    const raw = execSync(
      'security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null',
      { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }
    ).trim();
    const parsed = JSON.parse(raw);
    return parsed?.claudeAiOauth?.accessToken || parsed?.accessToken || parsed?.access_token || null;
  } catch { return null; }
}

// Anthropic Usage APIをバックグラウンドで呼び出し（親プロセスから切り離し）
function fetchUsageInBackground() {
  const token = getOAuthToken();
  if (!token) return;

  // curlを切り離しプロセスで実行し、結果をキャッシュに書き込む
  const script = `
    curl -s -m 5 -H "Authorization: Bearer ${token}" \
      -H "anthropic-beta: oauth-2025-04-20" \
      "https://api.anthropic.com/api/oauth/usage" 2>/dev/null | \
    node -e "
      let d='';
      process.stdin.on('data',c=>d+=c);
      process.stdin.on('end',()=>{
        try{
          const j=JSON.parse(d);
          const o={
            sessionUsage:j.five_hour?.utilization,
            sessionResetAt:j.five_hour?.resets_at,
            weeklyUsage:j.seven_day?.utilization,
            weeklyResetAt:j.seven_day?.resets_at
          };
          require('fs').mkdirSync('${CACHE_DIR}',{recursive:true});
          require('fs').writeFileSync('${USAGE_CACHE}',JSON.stringify(o));
        }catch{}
      });
    "
  `;
  const child = spawn('bash', ['-c', script], {
    detached: true,
    stdio: 'ignore'
  });
  child.unref();
}

// Git情報取得
function getGitInfo(cwd) {
  try {
    execSync('git rev-parse --is-inside-work-tree', { cwd, stdio: ['pipe', 'pipe', 'pipe'] });
    let repoName;
    try {
      const url = execSync('git remote get-url origin', { cwd, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
      repoName = path.basename(url, '.git');
    } catch {
      repoName = path.basename(execSync('git rev-parse --show-toplevel', { cwd, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim());
    }
    let branch;
    try {
      branch = execSync('git symbolic-ref --short HEAD', { cwd, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
    } catch {
      branch = execSync('git rev-parse --short HEAD', { cwd, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
    }
    return { repoName, branch };
  } catch { return { repoName: null, branch: null }; }
}

// リセット時刻フォーマット
function fmtResetTime(isoStr) {
  if (!isoStr) return '-';
  try {
    const d = new Date(isoStr);
    const h = d.getHours();
    const ampm = h >= 12 ? 'pm' : 'am';
    const h12 = h % 12 || 12;
    return `${h12}${ampm}`;
  } catch { return '-'; }
}

function fmtResetDate(isoStr) {
  if (!isoStr) return '-';
  try {
    const d = new Date(isoStr);
    const m = d.getMonth() + 1;
    const day = d.getDate();
    const h = d.getHours();
    const ampm = h >= 12 ? 'pm' : 'am';
    const h12 = h % 12 || 12;
    return `${m}/${day} ${h12}${ampm}`;
  } catch { return '-'; }
}

// プログレスバー構築
function buildBar(pct, width = 20) {
  const filled = Math.round(pct * width / 100);
  return '\u2588'.repeat(filled) + '\u2591'.repeat(width - filled);
}

// メイン
let input = '';
process.stdin.on('data', c => input += c);
process.stdin.on('end', () => {
  try {
    const data = JSON.parse(input);
    const cwd = data.workspace?.current_dir || data.cwd || process.cwd();
    const modelDisplay = data.model?.display_name || '?';
    const modelId = data.model?.id || '';
    // モデルバージョンを抽出 (例: claude-opus-4-6 -> 4.6)
    const verMatch = modelId.match(/(\d+)-(\d+)(?:-\d{8})?$/);
    const modelVer = verMatch ? `${verMatch[1]}.${verMatch[2]}` : '';
    // display_nameに既にバージョンが含まれていたら重複しない
    const fullModel = (modelVer && !modelDisplay.includes(modelVer)) ? `${modelDisplay} ${modelVer}` : modelDisplay;

    // effortレベルをsettings.jsonから取得
    let effort = '';
    try {
      const settings = JSON.parse(fs.readFileSync(path.join(HOME, '.claude', 'settings.json'), 'utf8'));
      effort = settings.effortLevel || '';
    } catch {}

    const pct = Math.floor(data.context_window?.used_percentage || 0);
    const shortPath = cwd.replace(HOME, '~');

    // Git
    const git = getGitInfo(cwd);

    // 使用量データ（キャッシュから読む。古ければバックグラウンドで更新）
    let usage = readCache(USAGE_CACHE, USAGE_MAX_AGE);
    if (!usage) {
      fetchUsageInBackground();
      usage = readCache(USAGE_CACHE, USAGE_MAX_AGE * 10); // 古いキャッシュでもフォールバック
    }


    const SEP = `  ${D}\u2502${R}  `;

    // === カレントディレクトリ ===
    console.log(`${CYAN}${shortPath}${R}`);

    // === リポジトリ / ブランチ ===
    if (git.repoName) {
      console.log(`${GREEN}${B}${git.repoName}${R} ${D}/${R} ${YELLOW}${git.branch}${R}`);
    }

    console.log('');

    // === プログレスバー + コンテキスト% + モデル ===
    const barColor = pct >= 80 ? RED : pct >= 50 ? YELLOW : GREEN;
    const bar = buildBar(pct);
    const effortStr = effort ? `  ${D}[${effort}]${R}` : '';
    console.log(`${barColor}${bar}${R}  ${B}${pct}%${R}${SEP}${MAG}${fullModel}${R}${effortStr}`);

    // === 5h/7d 使用量 ===
    if (usage && (usage.sessionUsage != null || usage.weeklyUsage != null)) {
      const h5 = usage.sessionUsage != null ? Math.round(usage.sessionUsage) : '-';
      const d7 = usage.weeklyUsage != null ? Math.round(usage.weeklyUsage) : '-';
      const h5Reset = fmtResetTime(usage.sessionResetAt);
      const d7Reset = fmtResetDate(usage.weeklyResetAt);
      const h5Color = h5 !== '-' && h5 >= 80 ? RED : h5 !== '-' && h5 >= 50 ? YELLOW : GREEN;
      const d7Color = d7 !== '-' && d7 >= 80 ? RED : d7 !== '-' && d7 >= 50 ? YELLOW : GREEN;
      console.log(`${D}5h${R} ${h5Color}${B}${h5}%${R} ${D}(${h5Reset})${R}${SEP}${D}7d${R} ${d7Color}${B}${d7}%${R} ${D}(${d7Reset})${R}`);
    } else {
      console.log(`${D}5h --${R}${SEP}${D}7d --${R}`);
    }

  } catch (e) {
    console.log(`${RED}statusline error: ${e.message}${R}`);
  }
});
