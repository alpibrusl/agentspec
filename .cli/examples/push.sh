#!/usr/bin/env bash
# Examples for: push

# Push to local registry
agentspec push researcher.agent

# Push to remote registry
agentspec push researcher.agent --registry http://localhost:3000

# JSON output
agentspec push researcher.agent --output json
