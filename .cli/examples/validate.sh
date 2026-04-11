#!/usr/bin/env bash
# Examples for: validate

# Validate a single file
agentspec validate researcher.agent

# Validate a directory agent
agentspec validate ./researcher/

# JSON output
agentspec validate researcher.agent --output json
