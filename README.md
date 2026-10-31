# erc1155-token-sim

ERC-1155 multi-token simulator in pure Python (EIP-1155).

A single contract holding many token types at once: fungible tokens,
non-fungible tokens (supply of 1), and anything in between. One approval
covers every token id, and batch transfers move many ids in one call.

## Features

- `mint` / `mint_batch` / `burn` / `burn_batch` with per-id total supply
- `safe_transfer_from` / `safe_batch_transfer_from` — batch transfers are
  atomic: if any leg fails, nothing moves
- `set_approval_for_all` / `is_approved_for_all` — one operator approval
  covers all token ids; `transfer_as` enforces it
- `balance_of` / `balance_of_batch`, `holders_of` (richest first)
- `uri` metadata templating (`{id}` substitution)
- Zero-address, insufficient-balance, and length-mismatch guards
- Append-only event audit log (`TransferSingle`, `TransferBatch`, `ApprovalForAll`)

## Usage

```python
from erc1155 import ERC1155Token

t = ERC1155Token()
t.mint_batch("alice", [1, 2], [100, 1])  # id 1 fungible, id 2 NFT-like
t.set_approval_for_all("alice", "carol", True)
t.transfer_as("carol", "alice", "bob", 1, 25)
t.safe_batch_transfer_from("alice", "bob", [1, 2], [10, 1])
print(t.balance_of("bob", 1))  # 35
```

## Run

```sh
python3 erc1155.py           # demo
python3 erc1155.py --test   # doctests
```

No dependencies. Python 3.8+.
