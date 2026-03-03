#!/usr/bin/env python3
"""Claude Code会話履歴をObsidianノートとして自動保存するフックスクリプト。

対応イベント: SessionStart, Stop, SessionEnd
環境変数からフック情報を取得し、セッションごとに1つのMarkdownファイルを管理する。
"""

import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ============================================
# 定数
# ============================================
JST = timezone(timedelta(hours=9))
OBSIDIAN_VAULT = Path.home() / "Documents" / "my_life"
OUTPUT_BASE = OBSIDIAN_VAULT / "claudecode"
STATE_FILE = Path.home() / ".claude" / "obsidian-hook-state.json"
LOG_FILE = Path.home() / ".claude" / "logs" / "obsidian-save.log"

# system-reminderなどのタグを除去する正規表現
SYSTEM_TAG_PATTERN = re.compile(
    r"<(?:system-reminder|command-name|local-command|task-notification)>.*?"
    r"</(?:system-reminder|command-name|local-command|task-notification)>",
    re.DOTALL,
)

# ============================================
# ユーティリティ
# ============================================

def log_error(msg: str) -> None:
    """エラーをログファイルに記録する。"""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def load_state() -> dict:
    """状態ファイルを読み込む。"""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state: dict) -> None:
    """状態ファイルを保存する。"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def read_hook_input() -> dict:
    """stdinからフック入力JSONを読み取る。"""
    try:
        data = sys.stdin.read()
        if data.strip():
            return json.loads(data)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def parse_timestamp(ts_str: str) -> datetime | None:
    """ISO形式のタイムスタンプをパースする。"""
    if not ts_str:
        return None
    try:
        # Python 3.11+のfromisoformatはタイムゾーン付きに対応
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        try:
            # フォールバック: Zサフィックス対応
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None


def format_time(ts_str: str) -> str:
    """タイムスタンプからHH:MM:SS形式のJST時刻を返す。"""
    dt = parse_timestamp(ts_str)
    if dt:
        return dt.astimezone(JST).strftime("%H:%M:%S")
    return ""


# ============================================
# Markdownフォーマット
# ============================================

def clean_text(text: str) -> str:
    """system-reminderなどのタグを除去する。"""
    return SYSTEM_TAG_PATTERN.sub("", text).strip()




def should_skip_message(entry: dict, session_id: str) -> bool:
    """メッセージをスキップすべきか判定する。"""
    msg_type = entry.get("type", "")

    # user/assistant以外はスキップ
    if msg_type not in ("user", "assistant"):
        return True

    # メタメッセージをスキップ
    if entry.get("isMeta", False):
        return True

    # サブエージェントのメッセージをスキップ
    if entry.get("isSidechain", False):
        return True

    # セッションIDの不一致をスキップ
    entry_session = entry.get("sessionId", "")
    if entry_session and session_id and entry_session != session_id:
        return True

    return False


def format_entry(entry: dict) -> str | None:
    """JSONLの1エントリをMarkdownにフォーマットする。"""
    msg_type = entry.get("type", "")
    message = entry.get("message", {})
    content = message.get("content", "")
    timestamp = entry.get("timestamp", "")
    time_str = format_time(timestamp)

    if msg_type == "user":
        # contentが文字列の場合
        if isinstance(content, str):
            text = clean_text(content)
            if not text:
                return None
            # ノイズタグを含むメッセージをスキップ
            if re.search(r"<(?:local-command|command-name|system-reminder|task-notification)>", text):
                return None
            header = f"### {time_str} \U0001f464 User\n\n" if time_str else "### \U0001f464 User\n\n"
            return header + text + "\n"

        # contentがリストの場合、テキストブロックのみ抽出
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    cleaned = clean_text(block.get("text", ""))
                    if cleaned and not re.search(
                        r"<(?:local-command|command-name|system-reminder|task-notification)>", cleaned
                    ):
                        text_parts.append(cleaned)

            if text_parts:
                header = f"### {time_str} \U0001f464 User\n\n" if time_str else "### \U0001f464 User\n\n"
                return header + "\n".join(text_parts) + "\n"
            return None

        return None

    elif msg_type == "assistant":
        if not isinstance(content, list):
            return None

        parts = []
        has_text = False

        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")

            if block_type == "text":
                text = clean_text(block.get("text", ""))
                if text and not text.startswith("No response requested"):
                    if not has_text:
                        header = f"### {time_str} \U0001f916 Claude\n\n" if time_str else "### \U0001f916 Claude\n\n"
                        parts.append(header)
                        has_text = True
                    parts.append(text + "\n")

            # tool_use, thinking, server_tool_use等はスキップ

        return "\n".join(parts) if parts else None

    return None


# ============================================
# ファイル生成
# ============================================

def generate_frontmatter(session_id: str, cwd: str, start_time: datetime) -> str:
    """Markdownファイルのfrontmatterを生成する。"""
    return (
        "---\n"
        f"session_id: {session_id}\n"
        f"project: {cwd}\n"
        f"time_start: {start_time.astimezone(JST).isoformat()}\n"
        "time_end: \"\"\n"
        "changed_files: []\n"
        "tags:\n"
        "  - claude-code\n"
        "---\n\n"
    )


def generate_metadata_table(session_id: str, cwd: str, start_time: datetime) -> str:
    """メタデータテーブルを生成する。"""
    date_str = start_time.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S")
    return (
        "| Key | Value |\n"
        "|---|---|\n"
        f"| Session | `{session_id[:8]}` |\n"
        f"| Project | `{cwd}` |\n"
        f"| Started | {date_str} |\n\n"
        "---\n\n"
        "## Conversation Log\n\n"
    )


def create_initial_file(session_id: str, cwd: str, start_time: datetime) -> Path:
    """初期Markdownファイルを作成する。"""
    date_dir = start_time.astimezone(JST).strftime("%Y%m%d")
    time_prefix = start_time.astimezone(JST).strftime("%H%M%S")
    short_id = session_id[:8]

    output_dir = OUTPUT_BASE / date_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{time_prefix}_{short_id}.md"
    output_path = output_dir / filename

    frontmatter = generate_frontmatter(session_id, cwd, start_time)
    metadata = generate_metadata_table(session_id, cwd, start_time)

    output_path.write_text(frontmatter + metadata, encoding="utf-8")
    return output_path


# ============================================
# JSONL処理
# ============================================

def read_jsonl_lines(path: str, start_line: int = 0) -> list[tuple[int, dict]]:
    """JSONLファイルからstart_line以降の行を読み込む。"""
    results = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    results.append((i, json.loads(line)))
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError):
        pass
    return results


def append_messages(output_path: Path, entries: list[tuple[int, dict]], session_id: str) -> None:
    """フォーマットしたメッセージをMarkdownファイルに追記する。"""
    parts = []
    for _line_num, entry in entries:
        if should_skip_message(entry, session_id):
            continue
        formatted = format_entry(entry)
        if formatted:
            parts.append(formatted)

    if parts:
        with open(output_path, "a", encoding="utf-8") as f:
            f.write("\n---\n\n".join(parts) + "\n\n---\n\n")


def extract_changed_files(entries: list[tuple[int, dict]]) -> list[str]:
    """tool_useからファイルパスを抽出する。"""
    files = set()
    for _line_num, entry in entries:
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message", {})
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            inp = block.get("input", {})
            if not isinstance(inp, dict):
                continue
            # 各ツールのファイルパスパラメータを抽出
            for key in ("file_path", "path", "filePath", "notebook_path"):
                val = inp.get(key, "")
                if val and isinstance(val, str) and "/" in val:
                    files.add(val)
    return sorted(files)


def update_frontmatter_end(output_path: Path, end_time: datetime, changed_files: list[str]) -> None:
    """frontmatterのtime_endとchanged_filesを更新する。"""
    try:
        text = output_path.read_text(encoding="utf-8")
    except OSError:
        return

    # time_endを更新
    end_str = end_time.astimezone(JST).isoformat()
    text = re.sub(r'time_end: ".*?"', f'time_end: "{end_str}"', text, count=1)

    # changed_filesを更新
    if changed_files:
        files_yaml = "\n".join(f"  - \"{f}\"" for f in changed_files[:50])  # 最大50ファイル
        text = re.sub(r"changed_files: \[.*?\]", f"changed_files:\n{files_yaml}", text, count=1)

    output_path.write_text(text, encoding="utf-8")


# ============================================
# イベントハンドラ
# ============================================

def ensure_initialized(session_id: str, transcript_path: str, cwd: str, state: dict) -> tuple[dict, Path]:
    """セッションが初期化されていなければ初期化する（resume対応）。"""
    if session_id in state:
        return state, Path(state[session_id]["output_path"])

    now = datetime.now(JST)

    # transcript_pathの最初の行からtimestampを取得して開始時刻を推定
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line:
                first_entry = json.loads(first_line)
                ts = parse_timestamp(first_entry.get("timestamp", ""))
                if ts:
                    now = ts
    except (OSError, json.JSONDecodeError):
        pass

    output_path = create_initial_file(session_id, cwd, now)
    state[session_id] = {
        "output_path": str(output_path),
        "last_line": 0,
        "start_time": now.isoformat(),
    }
    save_state(state)
    return state, output_path


def handle_session_start(hook_input: dict) -> None:
    """SessionStartイベントの処理。"""
    session_id = hook_input.get("session_id", "")
    cwd = hook_input.get("cwd", "")
    if not session_id:
        return

    state = load_state()
    now = datetime.now(JST)

    output_path = create_initial_file(session_id, cwd, now)
    state[session_id] = {
        "output_path": str(output_path),
        "last_line": 0,
        "start_time": now.isoformat(),
    }
    save_state(state)
    log_error(f"SessionStart: {session_id[:8]} -> {output_path}")


def handle_stop(hook_input: dict) -> None:
    """Stopイベントの処理。新規行を追記する。"""
    session_id = hook_input.get("session_id", "")
    transcript_path = hook_input.get("transcript_path", "")
    cwd = hook_input.get("cwd", "")
    if not session_id or not transcript_path:
        return

    state = load_state()

    # SessionStartなしでStopが来た場合（resume等）は初期化
    state, output_path = ensure_initialized(session_id, transcript_path, cwd, state)

    last_line = state[session_id].get("last_line", 0)
    entries = read_jsonl_lines(transcript_path, last_line)

    if entries:
        append_messages(output_path, entries, session_id)
        new_last = entries[-1][0] + 1  # 次の開始行
        state[session_id]["last_line"] = new_last
        save_state(state)


def handle_session_end(hook_input: dict) -> None:
    """SessionEndイベントの処理。残りの行を追記し、frontmatterを更新する。"""
    session_id = hook_input.get("session_id", "")
    transcript_path = hook_input.get("transcript_path", "")
    cwd = hook_input.get("cwd", "")
    if not session_id or not transcript_path:
        return

    state = load_state()

    # SessionStartなしの場合に対応
    state, output_path = ensure_initialized(session_id, transcript_path, cwd, state)

    # 残りの行を追記
    last_line = state[session_id].get("last_line", 0)
    entries = read_jsonl_lines(transcript_path, last_line)

    if entries:
        append_messages(output_path, entries, session_id)
        new_last = entries[-1][0] + 1
        state[session_id]["last_line"] = new_last

    # 全行を読み込んでchanged_filesを抽出
    all_entries = read_jsonl_lines(transcript_path, 0)
    changed_files = extract_changed_files(all_entries)

    # frontmatter更新
    end_time = datetime.now(JST)
    update_frontmatter_end(output_path, end_time, changed_files)

    save_state(state)
    log_error(f"SessionEnd: {session_id[:8]} -> {output_path}")


# ============================================
# メイン
# ============================================

def main() -> None:
    hook_input = read_hook_input()
    event_name = hook_input.get("hook_event_name", "")

    if event_name == "SessionStart":
        handle_session_start(hook_input)
    elif event_name == "Stop":
        handle_stop(hook_input)
    elif event_name == "SessionEnd":
        handle_session_end(hook_input)
    else:
        log_error(f"Unknown event: {event_name}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
    # フック失敗がClaude Code本体に影響しないよう常にexit 0
    sys.exit(0)
