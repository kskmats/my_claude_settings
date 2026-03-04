#!/usr/bin/env python3
"""MCP設定同期スクリプト

~/.claude.json から mcpServers セクションを抽出し、
機密情報をマスキングしてリポジトリ内の .claude.json に書き出す。
"""

import json
import re
import sys
from pathlib import Path

# --- ホワイトリスト定義 ---

# 一般的な安全な値
SAFE_VALUES = {"true", "false", "development", "production"}

# 値なしパススルー、または値が安全な環境変数キー
PASSTHROUGH_ENV_KEYS = {
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "NO_PROXY",
    "no_proxy",
    "NODE_ENV",
}

# 機能設定用の環境変数キー（値ごとマスキングしない）
FEATURE_CONFIG_ENV_KEYS = {"ENABLE_TOOLSETS"}

# コンテナ内の標準パス（マスキングしない）
STANDARD_CONTAINER_PATHS = {"/etc/ssl/certs/ca-certificates.crt"}

# 公開レジストリのプレフィックス
PUBLIC_IMAGE_PREFIXES = ("hashicorp/", "ghcr.io/")

# 値を取る Docker フラグ
DOCKER_FLAGS_WITH_VALUE = {
    "-v",
    "-e",
    "--pull",
    "--name",
    "-p",
    "--network",
    "--entrypoint",
    "-w",
    "--workdir",
}

# 大文字のまま保持するアクロニム
ACRONYMS = {
    "API",
    "URL",
    "CA",
    "SSL",
    "HTTP",
    "HTTPS",
    "MCP",
    "ID",
    "IP",
    "DNS",
    "SSH",
    "TLS",
    "CERT",
}

# 個人パスのパターン
PERSONAL_PATH_PATTERNS = ["/Users/", "${HOME}/", "$HOME/", "/home/", "~/"]


def key_to_placeholder(key: str) -> str:
    """環境変数名をプレースホルダーに変換

    例: SLACK_USER_TOKEN -> Slack User Token
        BACKLOG_API_KEY -> Backlog API Key
    """
    words = key.split("_")
    return " ".join(
        w.upper() if w.upper() in ACRONYMS else w.capitalize() for w in words
    )


def server_name_to_title(name: str) -> str:
    """サーバー名をタイトルケースに変換

    例: backlog -> Backlog
        slack-explorer-mcp -> Slack Explorer Mcp
    """
    words = name.split("-")
    return " ".join(w.capitalize() for w in words)


def is_personal_path(path: str) -> bool:
    """パスが個人的なパスかどうかを判定"""
    return any(p in path for p in PERSONAL_PATH_PATTERNS)


def is_public_image(image: str) -> bool:
    """Docker イメージが公開レジストリかどうかを判定"""
    return any(image.startswith(prefix) for prefix in PUBLIC_IMAGE_PREFIXES)


def should_mask_env_value(key: str, value: str) -> bool:
    """環境変数の値をマスキングすべきかどうかを判定"""
    if key in PASSTHROUGH_ENV_KEYS:
        return False
    if key in FEATURE_CONFIG_ENV_KEYS:
        return False
    if value in SAFE_VALUES:
        return False
    if value in STANDARD_CONTAINER_PATHS:
        return False
    return True


def process_docker_args(
    server_name: str, args: list,
) -> tuple[list, list[dict]]:
    """Docker args を処理してマスキング済み args と適用プレースホルダーを返す"""
    if not args or args[0] != "run":
        return args, []

    applied = []
    result = list(args)

    # --- Phase 1: ボリュームマウントを処理し、マスキングされたコンテナパスを収集 ---
    masked_container_paths: dict[str, str] = {}

    i = 0
    while i < len(result):
        if result[i] == "-v" and i + 1 < len(result):
            spec = result[i + 1]
            parts = spec.split(":")
            if len(parts) >= 2:
                host = parts[0]
                container = parts[1]
                options = ":".join(parts[2:]) if len(parts) > 2 else ""

                if is_personal_path(host):
                    new_host = "<CA_CERT_PATH>"
                    if container not in STANDARD_CONTAINER_PATHS:
                        masked_container_paths[container] = "<CA_CERT_CONTAINER_PATH>"
                        new_container = "<CA_CERT_CONTAINER_PATH>"
                    else:
                        new_container = container

                    new_spec = f"{new_host}:{new_container}"
                    if options:
                        new_spec += f":{options}"
                    result[i + 1] = new_spec
            i += 2
        elif result[i] in DOCKER_FLAGS_WITH_VALUE and i + 1 < len(result):
            i += 2
        else:
            i += 1

    # --- Phase 2: 環境変数を処理 ---
    i = 0
    while i < len(result):
        if result[i] == "-e" and i + 1 < len(result):
            env_spec = result[i + 1]
            if "=" in env_spec:
                key, value = env_spec.split("=", 1)
                if value in masked_container_paths:
                    # マスキングされたコンテナパスと同じ値 -> 同じプレースホルダーに置換
                    result[i + 1] = f"{key}={masked_container_paths[value]}"
                elif should_mask_env_value(key, value):
                    ph_name = key_to_placeholder(key)
                    placeholder = f"<{ph_name}>"
                    result[i + 1] = f"{key}={placeholder}"
                    applied.append(
                        {
                            "placeholder": placeholder,
                            "description": f"{server_name}の{key}",
                        }
                    )
            # else: 値なしパススルー（-e HTTP_PROXY など）はそのまま
            i += 2
        elif result[i] in DOCKER_FLAGS_WITH_VALUE and i + 1 < len(result):
            i += 2
        else:
            i += 1

    # --- Phase 3: Docker イメージ（最後の引数）を処理 ---
    last_idx = len(result) - 1
    if last_idx > 0:
        image = result[last_idx]
        if not image.startswith("-") and ("/" in image or ":" in image):
            if not is_public_image(image):
                title = server_name_to_title(server_name)
                placeholder = f"<{title} MCP Docker Image>"
                result[last_idx] = placeholder
                applied.append(
                    {
                        "placeholder": placeholder,
                        "description": f"{server_name}のDockerイメージ",
                    }
                )

    # --- 証明書関連のプレースホルダーを applied に追加 ---
    result_str = json.dumps(result)
    if "<CA_CERT_PATH>" in result_str:
        applied.append(
            {
                "placeholder": "<CA_CERT_PATH>",
                "description": "ホスト側のCA証明書ファイルパス",
            }
        )
    if "<CA_CERT_CONTAINER_PATH>" in result_str:
        applied.append(
            {
                "placeholder": "<CA_CERT_CONTAINER_PATH>",
                "description": "コンテナ内のCA証明書マウント先パス",
            }
        )

    return result, applied


def process_json_values(
    server_name: str, data: dict,
) -> tuple[dict, list[dict]]:
    """JSON辞書内の値をマスキング（headers, env 用）"""
    applied = []
    result = {}

    for key, value in data.items():
        if isinstance(value, str):
            # 既にプレースホルダーならそのまま
            if value.startswith("<") and value.endswith(">"):
                result[key] = value
            else:
                placeholder = f"<{key}>"
                result[key] = placeholder
                applied.append(
                    {
                        "placeholder": placeholder,
                        "description": f"{server_name}の{key}",
                    }
                )
        else:
            result[key] = value

    return result, applied


def process_server(
    name: str, config: dict,
) -> tuple[dict, list[dict]]:
    """サーバー設定をマスキング"""
    result = dict(config)
    all_applied = []

    # Docker args を処理
    if "args" in result and result.get("command") == "docker":
        result["args"], applied = process_docker_args(name, result["args"])
        all_applied.extend(applied)

    # headers を処理
    if "headers" in result and isinstance(result["headers"], dict) and result["headers"]:
        result["headers"], applied = process_json_values(name, result["headers"])
        all_applied.extend(applied)

    # env を処理（空でない場合のみ）
    if "env" in result and isinstance(result["env"], dict) and result["env"]:
        result["env"], applied = process_json_values(name, result["env"])
        all_applied.extend(applied)

    return result, all_applied


def check_for_leaks(masked_data: dict) -> list[str]:
    """マスキング後のデータに機密情報が残っていないかチェック"""
    warnings = []
    json_str = json.dumps(masked_data)

    # 個人パスのチェック
    for pattern in PERSONAL_PATH_PATTERNS:
        if pattern in json_str:
            warnings.append(f"未マスキングの個人パスが検出されました: {pattern}")

    # トークンパターンのチェック
    token_patterns = [
        (r"xoxp-[0-9a-f\-]+", "Slackトークン"),
        (r"xoxb-[0-9a-f\-]+", "Slackボットトークン"),
        (r"sk-[a-zA-Z0-9]{20,}", "APIキー（sk-）"),
        (r"ctx7sk-[a-f0-9\-]+", "Context7 APIキー"),
    ]
    for pattern, desc in token_patterns:
        if re.search(pattern, json_str):
            warnings.append(f"未マスキングの{desc}が検出されました")

    return warnings


def main():
    home = Path.home()
    source_path = home / ".claude.json"
    script_dir = Path(__file__).resolve().parent
    repo_dir = script_dir.parent
    output_path = repo_dir / ".claude.json"

    # ソースファイルの読み込み
    if not source_path.exists():
        print(
            json.dumps(
                {
                    "error": f"{source_path}が見つかりません",
                    "applied": [],
                    "warnings": [],
                    "servers_synced": [],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)

    with open(source_path) as f:
        source = json.load(f)

    servers = source.get("mcpServers", {})
    if not servers:
        print(
            json.dumps(
                {
                    "error": "mcpServersセクションが見つかりません",
                    "applied": [],
                    "warnings": [],
                    "servers_synced": [],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(1)

    # 各サーバーを処理
    masked_servers = {}
    all_applied = []

    for name, config in servers.items():
        masked_config, applied = process_server(name, config)
        masked_servers[name] = masked_config
        all_applied.extend(applied)

    # プレースホルダーの重複排除
    seen = set()
    unique_applied = []
    for item in all_applied:
        if item["placeholder"] not in seen:
            seen.add(item["placeholder"])
            unique_applied.append(item)

    # リーク検出
    warnings = check_for_leaks(masked_servers)

    # マスキング済み設定を書き出し
    output_data = {"mcpServers": masked_servers}
    with open(output_path, "w") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=4)
        f.write("\n")

    # 結果を出力
    result = {
        "applied": unique_applied,
        "warnings": warnings,
        "servers_synced": list(masked_servers.keys()),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
