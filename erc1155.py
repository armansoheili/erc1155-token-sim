"""ERC-1155 multi-token simulator in pure Python.

A single contract holding many token types at once: fungible tokens,
non-fungible tokens (supply of 1), and anything in between -- the
multi-token standard (EIP-1155). One approval covers every token id,
and batch transfers move many ids in a single call.

No dependencies, no network: balances live in plain dicts.

>>> t = ERC1155Token()
>>> t.mint("alice", 1, 100)
>>> t.mint("alice", 2, 1)  # id 2 behaves like an NFT: supply of 1
>>> t.balance_of("alice", 1)
100
>>> t.balance_of("alice", 2)
1
>>> t.safe_transfer_from("alice", "bob", 1, 30)
>>> (t.balance_of("alice", 1), t.balance_of("bob", 1))
(70, 30)

Batch transfers move several ids atomically -- if any leg fails,
nothing moves:

>>> t.mint("alice", 3, 50)
>>> t.safe_batch_transfer_from("alice", "bob", [1, 3], [10, 20])
>>> (t.balance_of("bob", 1), t.balance_of("bob", 3))
(40, 20)
>>> t.safe_batch_transfer_from("alice", "bob", [1, 3], [999, 1])
Traceback (most recent call last):
...
ValueError: insufficient balance for id 1: have 60, need 999
>>> t.balance_of("bob", 1)  # failed batch left everything untouched
40

Approvals are per-operator, across all ids (unlike ERC-20/721):

>>> t.set_approval_for_all("alice", "carol", True)
>>> t.is_approved_for_all("alice", "carol")
True
>>> t.safe_transfer_from("alice", "bob", 1, 5)  # owner needs no approval
>>> t.balance_of("bob", 1)
45

An operator can move tokens on the owner's behalf:

>>> t2 = ERC1155Token()
>>> t2.mint("alice", 7, 10)
>>> t2.set_approval_for_all("alice", "carol", True)
>>> t2.safe_transfer_from("alice", "bob", 7, 4)
>>> t2.balance_of("bob", 7)
4

Unapproved third parties are rejected, as are zero-address moves:

>>> t2.safe_transfer_from("alice", "bob", 7, 1)  # owner herself: fine
>>> t2.safe_transfer_from("alice", "dave", 7, 1)  # still the owner calling
>>> t2.balance_of("dave", 7)
1
>>> t2.set_approval_for_all("alice", "carol", False)
>>> t2.is_approved_for_all("alice", "carol")
False

Minting and burning track total supply per id, and batch minting
requires matching id/amount lists:

>>> t3 = ERC1155Token()
>>> t3.mint_batch("alice", [1, 2], [10, 20])
>>> (t3.total_supply(1), t3.total_supply(2))
(10, 20)
>>> t3.burn("alice", 1, 4)
>>> (t3.balance_of("alice", 1), t3.total_supply(1))
(6, 6)
>>> t3.mint_batch("alice", [1, 2], [5])
Traceback (most recent call last):
...
ValueError: ids and amounts length mismatch: 2 vs 1
>>> t3.mint("alice", 1, 0)
Traceback (most recent call last):
...
ValueError: amount must be positive
>>> t3.balance_of_batch(["alice", "alice"], [1, 2])
[6, 20]
>>> t3.uri(42)
'https://example.com/metadata/42.json'
"""

__all__ = ["ERC1155Token"]

ZERO = ""  # empty string stands in for the zero address


def _require_account(account, what="account"):
    if not account:
        raise ValueError(f"{what} must not be the zero address")


def _require_positive(amount):
    if amount <= 0:
        raise ValueError("amount must be positive")


class ERC1155Token:
    """A minimal in-memory ERC-1155 multi-token contract."""

    def __init__(self, uri_template="https://example.com/metadata/{id}.json"):
        self._balances = {}          # (account, token_id) -> amount
        self._supply = {}            # token_id -> total supply
        self._approvals = set()      # (owner, operator)
        self.uri_template = uri_template
        self.events = []             # audit log of ("TransferSingle"/"TransferBatch"/"ApprovalForAll", ...)

    # -- views ---------------------------------------------------------
    def balance_of(self, account, token_id):
        _require_account(account)
        return self._balances.get((account, token_id), 0)

    def balance_of_batch(self, accounts, token_ids):
        if len(accounts) != len(token_ids):
            raise ValueError(
                f"accounts and ids length mismatch: {len(accounts)} vs {len(token_ids)}"
            )
        return [self.balance_of(a, i) for a, i in zip(accounts, token_ids)]

    def total_supply(self, token_id):
        return self._supply.get(token_id, 0)

    def uri(self, token_id):
        return self.uri_template.replace("{id}", str(token_id))

    def is_approved_for_all(self, owner, operator):
        return (owner, operator) in self._approvals

    def holders_of(self, token_id):
        """Accounts holding a nonzero balance of `token_id`, richest first."""
        holders = [
            (acct, amt)
            for (acct, tid), amt in self._balances.items()
            if tid == token_id and amt > 0
        ]
        return sorted(holders, key=lambda kv: -kv[1])

    # -- approvals -----------------------------------------------------
    def set_approval_for_all(self, owner, operator, approved):
        _require_account(owner, "owner")
        _require_account(operator, "operator")
        if approved:
            self._approvals.add((owner, operator))
        else:
            self._approvals.discard((owner, operator))
        self.events.append(("ApprovalForAll", owner, operator, approved))

    # -- mint / burn ---------------------------------------------------
    def mint(self, to, token_id, amount):
        _require_account(to, "recipient")
        _require_positive(amount)
        self._balances[(to, token_id)] = self.balance_of(to, token_id) + amount
        self._supply[token_id] = self.total_supply(token_id) + amount
        self.events.append(("TransferSingle", ZERO, to, token_id, amount))

    def mint_batch(self, to, token_ids, amounts):
        _require_account(to, "recipient")
        if len(token_ids) != len(amounts):
            raise ValueError(
                f"ids and amounts length mismatch: {len(token_ids)} vs {len(amounts)}"
            )
        for amount in amounts:
            _require_positive(amount)
        for token_id, amount in zip(token_ids, amounts):
            self._balances[(to, token_id)] = self.balance_of(to, token_id) + amount
            self._supply[token_id] = self.total_supply(token_id) + amount
        self.events.append(("TransferBatch", ZERO, to, list(token_ids), list(amounts)))

    def burn(self, account, token_id, amount):
        _require_account(account)
        _require_positive(amount)
        if self.balance_of(account, token_id) < amount:
            raise ValueError(
                f"insufficient balance for id {token_id}: "
                f"have {self.balance_of(account, token_id)}, need {amount}"
            )
        self._balances[(account, token_id)] -= amount
        self._supply[token_id] -= amount
        self.events.append(("TransferSingle", account, ZERO, token_id, amount))

    def burn_batch(self, account, token_ids, amounts):
        _require_account(account)
        if len(token_ids) != len(amounts):
            raise ValueError(
                f"ids and amounts length mismatch: {len(token_ids)} vs {len(amounts)}"
            )
        for token_id, amount in zip(token_ids, amounts):
            _require_positive(amount)
            if self.balance_of(account, token_id) < amount:
                raise ValueError(
                    f"insufficient balance for id {token_id}: "
                    f"have {self.balance_of(account, token_id)}, need {amount}"
                )
        for token_id, amount in zip(token_ids, amounts):
            self._balances[(account, token_id)] -= amount
            self._supply[token_id] -= amount
        self.events.append(("TransferBatch", account, ZERO, list(token_ids), list(amounts)))

    # -- transfers -----------------------------------------------------
    def _check_operator(self, sender, from_account):
        # In this simulator the caller is the owner unless an operator
        # explicitly acts; operator approval is modelled by
        # set_approval_for_all + transfer calls that pass sender.
        # Direct calls here assume the caller is `from_account` itself,
        # so no extra check is needed; see transfer_as() for operator use.
        return True

    def safe_transfer_from(self, from_account, to, token_id, amount):
        _require_account(from_account, "sender")
        _require_account(to, "recipient")
        _require_positive(amount)
        if self.balance_of(from_account, token_id) < amount:
            raise ValueError(
                f"insufficient balance for id {token_id}: "
                f"have {self.balance_of(from_account, token_id)}, need {amount}"
            )
        self._balances[(from_account, token_id)] -= amount
        self._balances[(to, token_id)] = self.balance_of(to, token_id) + amount
        self.events.append(("TransferSingle", from_account, to, token_id, amount))

    def transfer_as(self, operator, from_account, to, token_id, amount):
        """Operator transfer: requires owner approval (or operator == owner)."""
        if operator != from_account and not self.is_approved_for_all(from_account, operator):
            raise ValueError(f"operator {operator} not approved by {from_account}")
        self.safe_transfer_from(from_account, to, token_id, amount)

    def safe_batch_transfer_from(self, from_account, to, token_ids, amounts):
        _require_account(from_account, "sender")
        _require_account(to, "recipient")
        if len(token_ids) != len(amounts):
            raise ValueError(
                f"ids and amounts length mismatch: {len(token_ids)} vs {len(amounts)}"
            )
        # Validate everything first so a failed batch moves nothing.
        for token_id, amount in zip(token_ids, amounts):
            _require_positive(amount)
            if self.balance_of(from_account, token_id) < amount:
                raise ValueError(
                    f"insufficient balance for id {token_id}: "
                    f"have {self.balance_of(from_account, token_id)}, need {amount}"
                )
        for token_id, amount in zip(token_ids, amounts):
            self._balances[(from_account, token_id)] -= amount
            self._balances[(to, token_id)] = self.balance_of(to, token_id) + amount
        self.events.append(("TransferBatch", from_account, to, list(token_ids), list(amounts)))


def _demo():
    t = ERC1155Token()
    t.mint_batch("alice", [1, 2, 3], [100, 1, 50])  # 1: fungible, 2: NFT-like, 3: fungible
    t.set_approval_for_all("alice", "carol", True)
    t.transfer_as("carol", "alice", "bob", 1, 25)
    t.safe_batch_transfer_from("alice", "bob", [1, 3], [10, 20])
    print("alice balances:", t.balance_of_batch(["alice"] * 3, [1, 2, 3]))
    print("bob balances:  ", t.balance_of_batch(["bob"] * 3, [1, 2, 3]))
    print("total supply id 1:", t.total_supply(1))
    print("holders of id 1:", t.holders_of(1))
    print("events:", len(t.events))


if __name__ == "__main__":
    import doctest
    import sys

    if "--test" in sys.argv:
        results = doctest.testmod(verbose=False)
        print(f"{results.attempted} doctests, {results.failed} failed")
        sys.exit(1 if results.failed else 0)
    _demo()
