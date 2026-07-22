# Terminal character chat

`bunnyland chat` is a focused Textual character picker and conversation app. Without
`--server` it generates and hosts a world in the current process; no Bunnyland HTTP server
is needed. With `--server` it submits and polls the server's existing v1 chat jobs.

Character chat is available only while the character's current controller is an LLM. A
suspended, scripted, web-controlled, or otherwise unsupported character reports that state
instead of inventing a second dialogue system. Saved history remains visible, but the message
input becomes read-only. A signed-in administrator can choose one of the world's existing LLM
controllers and assign it from the Textual conversation screen; successful assignment refreshes
the screen and enables sending.

## Local Ollama

Install the `tui` and `llm` extras and run Ollama locally. The default endpoint is
`http://127.0.0.1:11434`:

```bash
uv run --all-extras bunnyland chat \
  --generator apartment-demo \
  --chat-provider ollama-local \
  --chat-model llama3.2
```

Override the endpoint with `--ollama-host` or `OLLAMA_HOST`. This mode can be fully
network-free when the model is already installed in the local Ollama daemon.

## Ollama Cloud and OpenRouter

Cloud credentials come only from the environment:

```bash
export OLLAMA_CLOUD_API_KEY='...'
uv run --all-extras bunnyland chat \
  --chat-provider ollama-cloud \
  --chat-model deepseek-v4-flash

export OPENROUTER_API_KEY='...'
uv run --all-extras bunnyland chat \
  --chat-provider openrouter \
  --chat-model openai/gpt-4.1-mini
```

`--openrouter-server-url` or `OPENROUTER_SERVER_URL` overrides the OpenRouter-compatible
endpoint. Missing cloud credentials are reported before the local world starts.

All terminal clients accept the same chat flags:

- `--chat-provider ollama-local|ollama-cloud|openrouter`
- `--chat-model MODEL`
- `--ollama-host URL`
- `--openrouter-server-url URL`
- `--no-chat`

Command-line values override environment endpoint values, which override saved values and
then defaults.

## Saved configuration

The first local Textual launch of `bunnyland tui`, `bunnyland repl`, or `bunnyland chat`
opens a provider/model setup screen. It writes a versioned file at
`$XDG_CONFIG_HOME/bunnyland/terminal.yml` (normally
`~/.config/bunnyland/terminal.yml`):

```yaml
version: 1
chat_enabled: true
chat_provider: ollama-local
chat_model: llama3.2
ollama_host: http://127.0.0.1:11434
openrouter_server_url: https://openrouter.ai/api/v1
```

The file never contains API keys. Choose **No chat** during setup, pass `--no-chat`, or set
`chat_enabled: false` to host a local terminal world without conversational inference.

## Local and remote examples

The default app presents a character picker. Local mode supports the normal generator and
seed selection flow:

```bash
uv run --all-extras bunnyland chat
uv run --all-extras bunnyland chat --generator lifesim-demo --seed 'a rainy block'
uv run --all-extras bunnyland chat --character Juniper
```

For a remote server, local provider settings are ignored and the setup screen is skipped:

```bash
uv run --all-extras bunnyland chat \
  --server https://play.example/v1 \
  --character Juniper \
  --username player
```

The remote authentication options match the TUI and REPL: `--username`,
`--password-stdin`, and `--token-file`. Character sheets open inside the conversation via
the **Sheet** button.

## Line-oriented mode

Use `--cli` to preserve a prompt suitable for a plain terminal or simple automation:

```bash
uv run --all-extras bunnyland chat --cli --generator apartment-demo --character Juniper
uv run --all-extras bunnyland chat --cli --server https://play.example/v1 --character Juniper
```

Local `--cli` mode cannot open the setup screen, so it requires saved configuration or an
explicit `--chat-provider` (and model when desired). Conversation history is shared with
the Textual clients and bounded to the latest 24 messages. Line-oriented chat prints that
history before the prompt and enforces the same controller rule as Textual chat. In read-only
mode, administrators (and local world hosts) can use `/controllers` to list existing LLM
controllers and `/controller <id>` to assign one. `/meta` or `/help` lists the available
client-side commands; these commands never send their text as character dialogue.
