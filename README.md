# Claude Code 共有設定

Claude Code のグローバル設定を共有するリポジトリ。

## セットアップ

このリポジトリを `~/.claude/` にクローンして利用する。

```bash
git clone <repository-url> ~/.claude
```

## 構成

```
~/.claude/
├── .claude.json          # MCP サーバー設定テンプレート
├── CLAUDE.md             # グローバルなカスタム指示
├── settings.json         # 権限・フック・プラグイン設定
├── scripts/              # スクリプトファイル
└── skills/               # Skills
```

## MCP Server の設定

`.claude.json` にMCPサーバーの設定テンプレートを格納している。
Claude Code のグローバルMCP設定は `~/.claude.json`（リポジトリ外）に保存されるため、必要なサーバー設定を手動でコピーする。

### 手順

1. `.claude.json` から必要な `mcpServers` の設定をコピー
2. `~/.claude.json` にマージ
3. `<...>` で囲まれた箇所を実際の値に置換

### マスキングされている値

| プレースホルダ | 説明 |
|--------------|------|
| `<CONTEXT7_API_KEY>` | Context7 の API キー |
| `<Slack User Token>` | Slack のユーザートークン |
| `<Backlog API Key>` | Backlog の API キー |
| `<Backlog Domain>` | Backlog のドメイン |
| `<Backlog MCP Docker Image>` | Backlog MCP サーバーの Docker イメージ |
| `<CA_CERT_PATH>` | ホスト側の CA 証明書ファイルパス |
| `<CA_CERT_CONTAINER_PATH>` | コンテナ内の CA 証明書マウント先パス |

## 設定のポイント

### 通知

`terminal-notifier` を利用して、Claude Code のイベント（許可待ち・入力待ち・タスク完了）をmacOS通知で受け取る。並列タスク実行時に特に有用。

- `Notification` フック: 許可待ち・入力待ちを通知
- `Stop` フック: タスク完了を通知

通知スクリプト: `scripts/notify.sh`

### YOLO モードでの禁止コマンド

`--dangerously-skip-permissions`（YOLOモード）使用時でも危険なコマンドをブロックする仕組み。

`settings.json` の `permissions.deny` に禁止パターンを定義し、`PreToolUse` フックで `scripts/deny-check.sh` を実行してチェックする。

禁止コマンドの例:

- `git config *`
- `rm -rf /*`
- `chmod 777 *`
- `gh repo delete:*`

複合コマンド（`&&`, `||`, `;` で連結）も各パートを分割してチェックする。

### 会話履歴の Obsidian 同期

Claude Code の会話履歴を自動で Obsidian Vault に Markdown ファイルとして保存する。

`SessionStart`・`Stop`・`SessionEnd` の各フックで `scripts/obsidian-save.py` を実行し、JSONL 形式のトランスクリプトを Obsidian 用 Markdown に変換・追記する。

[参考](https://qiita.com/K5K/items/b1dd8b92df682a37c829)