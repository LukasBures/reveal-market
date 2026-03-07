# Runbook: Key Rotation

Covers rotation of the relayer signing key and the pricing signer key.

---

## Relayer Key Rotation

The relayer key signs all on-chain transactions (commit, claim, lock-batches).

### When to rotate

- Key is suspected compromised
- Scheduled rotation (recommend every 90 days)
- Server migration

### Steps

#### 1. Generate a new key

```bash
# Generate a new EOA and note the address + private key
cast wallet new
# Output:
#   Address: 0xNEW_RELAYER_ADDRESS
#   Private key: 0xNEW_PRIVATE_KEY
```

#### 2. Fund the new address

The relayer needs ETH/ZEN for gas. Transfer from the old address or a funding wallet.

```bash
cast send \
  --rpc-url "${RPC_URL}" \
  --private-key "${OLD_RELAYER_KEY}" \
  "0xNEW_RELAYER_ADDRESS" \
  --value 0.1ether
```

#### 3. Authorize the new address in RelayerEscrow (if applicable)

If `RelayerEscrow` maintains an authorized relayer list:

```bash
cast send \
  --rpc-url "${RPC_URL}" \
  --private-key "${DEPLOYER_KEY}" \
  "${RELAYER_ESCROW_ADDRESS}" \
  "setRelayer(address)" \
  "0xNEW_RELAYER_ADDRESS"
```

#### 4. Update the prod secret and redeploy

Update `RELAYER_PRIVATE_KEY` in the production secrets store (Docker secret or secret manager).

```bash
# On prod server — update the secret file
echo "0xNEW_PRIVATE_KEY" > /run/secrets/relayer_private_key
chmod 400 /run/secrets/relayer_private_key

# Redeploy the relayer container
docker compose -f docker-compose.yml --env-file .env.production \
  up -d --no-deps --force-recreate relayer
```

#### 5. Verify

```bash
# Check relayer logs for the new address
docker compose logs relayer | grep "address\|signer\|account"

# Check /healthz
curl -sf http://localhost:8088/healthz | jq .
```

#### 6. Revoke old key authorization (if applicable)

Once the new key is confirmed working, remove the old address from `RelayerEscrow`.

---

## Pricing Signer Key Rotation

The pricing signer key signs quote digests in `/pricing/quote`.

### Impact of rotation

Outstanding signed quotes (issued before rotation) will fail signature verification
when a user submits them via `/trade/commit`. The default quote TTL is 15 minutes
(`RM_QUOTE_STORE_TTL_SECONDS=900`). Wait at least 15 minutes after deploying the
new key before considering old quotes fully expired.

### Steps

#### 1. Generate a new key

```bash
cast wallet new
# Note: Address: 0xNEW_SIGNER_ADDRESS, Private key: 0xNEW_PRIVATE_KEY
```

#### 2. Update `RM_AUTHORIZATION_SIGNER_PRIVATE_KEY` if also rotating authorization signer

These are separate keys; rotate independently unless both are compromised.

#### 3. Update the prod secret and redeploy the API

```bash
# Update secret
# Then:
docker compose -f docker-compose.yml --env-file .env.production \
  up -d --no-deps --force-recreate api
```

#### 4. Verify

```bash
# API healthz exposes signer address
curl -sf https://api.revealmarket.xyz/healthz | jq '.signer_address'
# Should show new address
```

#### 5. Wait for old quotes to expire

Wait 15+ minutes. Any commits using quotes signed by the old key will fail with
`invalid_quote_signature`. This is expected and resolves on its own.
