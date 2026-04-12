#!/usr/bin/env bash
# Examples for: pull

# Pull from local registry
agentspec pull ag1:abc123def456

# Pull from remote registry
agentspec pull abc123def456 --registry http://localhost:3000

# JSON output
agentspec pull ag1:abc123 --output json
