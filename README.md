[![Python application](https://github.com/FFD-Group/OrderEmailResender/actions/workflows/python-app.yml/badge.svg?branch=main)](https://github.com/FFD-Group/OrderEmailResender/actions/workflows/python-app.yml)

# OrderEmailResender
Poll the Magento API for unsent orders, check their comments to see if attempts have been made to resend (within a threshold) and either uses the API to trigger a resend or alerts admin and sends a backup email to the sales inbox with details.

## The Problem
Magento silently fails to send asynchronous order emails occassionally. Logging is not helpful without extensive and expensive extra modules or mail servers for log monitoring.

## This Script
This script attempts to resolve the problem by adding resilience to the order email sending by using Magento's own API to resend the order emails and if that fails multiple times the order details can be manually sent to the sales team.

### Program Flow
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
