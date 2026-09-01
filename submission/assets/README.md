# Submission assets

The release bundle places the catalog-bound `catalog-signatures.sqlite3` here.
Generate it from the exact scoring catalog with `scripts/build_signature_index.py`.
The binary stays ignored during development. The release builder verifies its
hash and catalog binding before adding it to the archive.
