---
name: linear-infra-task
description: インフラタスクをLinearに登録するスキル。「タスク登録して」「Linearにチケット作って」などの要求に使用する。
---

# Linear インフラタスク登録

ユーザーの指示に基づき、Linear の「デポ休-Infra」プロジェクトにインフラタスクを登録する。

## 固定パラメータ

| パラメータ | 値 |
|---|---|
| team | Nttdxpn-depokyu |
| project | デポ休-Infra |
| state | Todo |

## ワークフロー

### 1. ユーザーからの入力を整理

ユーザーが伝えたタスク内容から以下を判断する:

- **タイトル**: 簡潔かつ具体的（日本語）
- **優先度**: 1=Urgent, 2=High, 3=Normal, 4=Low
- **期限(dueDate)**: ISO形式（例: 2026-03-14）
- **blockedBy**: 依存するチケット（NTT-xxx 形式）があれば指定
- **description**: 下記テンプレートに従って記述

### 2. description テンプレート

```markdown
## 目的
<なぜこのタスクが必要か>

## 作業内容
- <具体的な作業項目をリストで記載>

## 完了条件
- <何が達成されたら完了か>

## 関連ファイル
- <関連する Terraform ファイルやドキュメントのパス>
```

### 3. ユーザーに確認

登録前に以下を提示して AskUserQuestion で確認を取る:
- タイトル
- 優先度
- 期限
- description の内容

### 4. Linear に登録

MCP の `mcp__linear__save_issue` を使って登録する。

```
mcp__linear__save_issue(
  title: <タイトル>,
  team: "Nttdxpn-depokyu",
  project: "デポ休-Infra",
  priority: <優先度>,
  dueDate: <期限>,
  state: "Todo",
  blockedBy: <依存チケット（あれば）>,
  description: <description>
)
```

### 5. 結果を報告

登録後、チケット番号（NTT-xxx）と URL をユーザーに伝える。

## 複数タスクの一括登録

ユーザーが複数タスクをまとめて依頼した場合:
- 1つずつ内容を提示し、AskUserQuestion で確認を取ってから登録する
- 一括登録（確認なしの自動登録）はしない

## 注意事項

- タスクの description は「中程度」の詳細度（目的・完了条件・関連ファイル）
- 粒度が細かすぎるタスク（単体モジュール適用など、すぐ終わるもの）は避け、適切にまとめる
- Infra ラベルが利用可能になった場合は labels に追加する
