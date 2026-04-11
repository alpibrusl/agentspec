#!/usr/bin/env bash
# Examples for: run

# Run a researcher agent
agentspec run researcher.agent

# Run with input
agentspec run researcher.agent --input 'quantum tunneling'

# Dry-run to see the plan
agentspec run researcher.agent --dry-run

# Verbose resolver output
agentspec run researcher.agent --verbose
