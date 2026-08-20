# #387 — least-privilege OpenBao policy for the v2-dev reviewer-proxy materializer AppRole.
#
# Grants ONLY read of the single KV-v2 value. Everything else is default-denied: sibling data paths,
# list, metadata (read/list), any sys/* path, and all write/create/update/delete/patch capabilities are
# NOT granted, so a token carrying only this policy cannot reach them. The cutover preflight proves the
# authorized read PASS plus the required denials (sibling read, data list, metadata read, metadata list,
# sys read, write/create, delete) live against loopback OpenBao before publication.
path "tanaghom/data/dev/reviewer-proxy" {
  capabilities = ["read"]
}
