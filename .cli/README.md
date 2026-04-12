# agentspec

Version: 0.1.0
ACLI version: 0.1.0

## Commands

### introspect

Output the full command tree as JSON for agent consumption.

### version

Show version information.

### skill

Generate a SKILLS.md file for agent bootstrapping.

### run

Resolve and run an agent from a .agent file or directory.

Idempotent: False

### validate

Validate a .agent file or directory against the schema.

Idempotent: True

### resolve

Show what would run without executing. Always verbose.

Idempotent: True

### extend

Scaffold a new agent that extends an existing one.

Idempotent: False

### push

Publish an agent to a registry (local or remote Noether registry).

Idempotent: True

### pull

Pull an agent from a registry (local or remote Noether registry).

Idempotent: True

### search

Search for agents in a remote Noether registry.

Idempotent: True

### schema

Print the JSON Schema for .agent files.

Idempotent: True

### init

Scaffold a new .agent project.

Idempotent: False

