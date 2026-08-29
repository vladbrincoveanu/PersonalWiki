# Agents

## Environment Setup

```bash
# Required environment variables for MiniMax API
export ANTHROPIC_AUTH_TOKEN=<your-token>
export ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic
export ANTHROPIC_MODEL=MiniMax-M2.7
```

## Commands

```bash
# Build
dotnet build Vke.sln

# Run tests
dotnet test Vke.sln

# Run CLI
dotnet run --project src/Vke.Cli -- ingest --url <url> --type <type> --domain <domain>
dotnet run --project src/Vke.Cli -- lint
```

## Tech Stack

- C# / .NET 10
- DuckDB.NET for graph storage
- MiniMax M2.7 via Anthropic API
- xUnit for tests
