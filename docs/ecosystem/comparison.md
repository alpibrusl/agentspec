# Comparison

How AgentSpec compares to similar projects.

## vs. gitagent (Lyzr AI)

| Feature | AgentSpec | gitagent |
|---|---|---|
| Manifest format | YAML, multi-format | YAML |
| Resolver | ✓ auto-negotiates env | ✗ |
| Inheritance | ✓ enforced merge strategies | partial (URL-based extends) |
| Trust enforcement | ✓ hardcoded restrict | ✗ |
| Signing/profiles | ✓ Ed25519 portfolios | ✗ |
| Registry | ✓ via Noether | proprietary |
| Owner | community (EUPL-1.2) | Lyzr AI (single company) |

gitagent has a clean format but no resolver, no profile system, and is tied to one vendor.

## vs. Agent Format (Snap Inc.)

| Feature | AgentSpec | Agent Format |
|---|---|---|
| Spec quality | ✓ comprehensive | ✓ clean |
| Resolver | ✓ | ✗ |
| Inheritance | ✓ | ✗ |
| Tooling | ✓ CLI + SDK | spec-only |
| Profiles | ✓ | ✗ |
| Active | ✓ | abandoned-ish |

Agent Format had a great spec but no working tooling. AgentSpec borrows the cleanest ideas and adds the missing pieces.

## vs. OSSA

| Feature | AgentSpec | OSSA |
|---|---|---|
| Lightweight | ✓ pip install | ✗ Drupal-based |
| Cryptographic verification | ✓ Ed25519 | ✓ chains |
| Discovery | semantic search | DNS-native |
| Complexity | medium | high |
| Audience | developers | enterprises |

OSSA is over-engineered for most use cases. AgentSpec aims for the 80% with less ceremony.

## vs. LangGraph / CrewAI / AutoGen

These are **orchestrators**, not standards:

| Feature | AgentSpec | LangGraph/CrewAI/AutoGen |
|---|---|---|
| Manifest format | ✓ universal | each has its own |
| Cross-orchestrator portability | ✓ | ✗ |
| Resolver | ✓ | partial |
| Profiles | ✓ | varies |

AgentSpec is **complementary**. You can use LangGraph/CrewAI/AutoGen as the orchestrator and AgentSpec as the agent definition format. The `.agent` file becomes portable across orchestrators.

## vs. MCP (Model Context Protocol)

MCP is about **tool/resource exposure** to agents. AgentSpec is about **agent definition**.

| Layer | Standard |
|---|---|
| Tools/resources for agents | MCP |
| Agent definition | AgentSpec |
| Orchestration | LangGraph, CrewAI, caloron-noether, ... |
| Composition | Noether |

They stack:

```
caloron-noether  (orchestrator)
      ↓
agentspec  (defines the agents)
      ↓
mcp servers  (provide tools to the agents)
      ↓
noether  (composes verified stages)
```

Use them together.

## vs. Docker / OCI

The analogy is direct:

| Docker / OCI | AgentSpec |
|---|---|
| `Dockerfile` | `.agent` file |
| `docker build` | `agentspec resolve` |
| `docker run` | `agentspec run` |
| `docker pull/push` | `agentspec pull/push` |
| Docker Hub | registry.agentspec.dev (via noether-cloud) |
| Image hash | content hash (ag1:xxx) |
| Image layers | inheritance chain |

But agents are not containers — they're declarations resolved at runtime. The closest analogy is **Helm charts for AI agents**: declarative, parameterized, registry-distributable.
