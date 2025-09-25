# OrderEmailResender
Poll the Magento API for unsent orders, check their comments to see if attempts have been made to resend (within a threshold) and either uses the API to trigger a resend or alerts admin and sends a backup email to the sales inbox with details.

```mermaid
graph TD;
    script((Start)) --> web[Fetch unsent orders];
    web --> worktodo{Unsent orders?}
    worktodo --> |Yes| order[First unsent order]
    worktodo --> |No| j
    order --> a{"`Exceeds max
            resend attempts?`"};
    a --> b[Yes];
    a --> c[No];
    b --> d[Alert admin]
    d --> e["`Send order
            details manually`"]
    c --> f[Ask Magento to resend]
    f --> g[Add comment to order]
    g --> h[Log outcome]
    e --> h
    h --> i[Next unsent order?]
    i --> |Yes| a
    i --> |No| j(((Stop)))
```