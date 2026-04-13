# A2A Protocol: Authentication & Security Specification Research

**Source**: https://a2a-protocol.org/latest/specification/ (and normative proto at
`specification/a2a.proto` in https://github.com/google/A2A)

**Date**: 2026-03-06

---

## 1. Overview

The A2A protocol defines authentication and security in two places:

- **Section 4.5** -- Security Objects (data model for declaring auth schemes)
- **Section 7** -- Authentication and Authorization (normative requirements)

Security is declared per-agent via the **Agent Card** (`securitySchemes` + `security` fields).
The protocol is modeled closely on OpenAPI 3.2 Security Scheme Objects.

---

## 2. Security Scheme Types (Section 4.5)

The normative source is the proto definition. `SecurityScheme` is a **discriminated union**
(protobuf `oneof`) supporting six scheme types:

```protobuf
message SecurityScheme {
  oneof scheme {
    APIKeySecurityScheme api_key_security_scheme = 1;
    HTTPAuthSecurityScheme http_auth_security_scheme = 2;
    OAuth2SecurityScheme oauth2_security_scheme = 3;
    OpenIdConnectSecurityScheme open_id_connect_security_scheme = 4;
    MutualTlsSecurityScheme mtls_security_scheme = 5;
  }
}
```

### 2.1 APIKeySecurityScheme

API key passed via header, query parameter, or cookie.

```protobuf
message APIKeySecurityScheme {
  string description = 1;                                    // optional
  string location = 2 [(google.api.field_behavior) = REQUIRED]; // "query" | "header" | "cookie"
  string name = 3 [(google.api.field_behavior) = REQUIRED];    // parameter name
}
```

- `location` (REQUIRED): Where the API key is sent. Valid values: `"query"`, `"header"`, `"cookie"`.
- `name` (REQUIRED): The name of the header, query parameter, or cookie (e.g., `"X-API-Key"`).

### 2.2 HTTPAuthSecurityScheme

Standard HTTP authentication (RFC 7235), including Bearer tokens.

```protobuf
message HTTPAuthSecurityScheme {
  string description = 1;                                    // optional
  string scheme = 2 [(google.api.field_behavior) = REQUIRED]; // e.g. "Bearer", "Basic"
  string bearer_format = 3;                                  // optional hint, e.g. "JWT"
}
```

- `scheme` (REQUIRED): IANA-registered HTTP authentication scheme name (case-insensitive).
  Common values: `"Bearer"`, `"Basic"`.
- `bearer_format` (optional): Documentation hint for token format (e.g., `"JWT"`).
  Does not affect protocol behavior.

### 2.3 OAuth2SecurityScheme

OAuth 2.0 with explicit flow configuration.

```protobuf
message OAuth2SecurityScheme {
  string description = 1;                                    // optional
  OAuthFlows flows = 2 [(google.api.field_behavior) = REQUIRED];
  string oauth2_metadata_url = 3;                            // optional, RFC 8414
}
```

- `flows` (REQUIRED): The OAuth 2.0 flow configuration (see Section 2.7 below).
- `oauth2_metadata_url` (optional): URL to OAuth2 authorization server metadata per
  [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414). TLS required.

### 2.4 OpenIdConnectSecurityScheme

OpenID Connect discovery-based authentication.

```protobuf
message OpenIdConnectSecurityScheme {
  string description = 1;                                    // optional
  string open_id_connect_url = 2 [(google.api.field_behavior) = REQUIRED];
}
```

- `open_id_connect_url` (REQUIRED): The
  [OpenID Connect Discovery URL](https://openid.net/specs/openid-connect-discovery-1_0.html)
  for the provider's metadata (e.g., `https://accounts.google.com/.well-known/openid-configuration`).

### 2.5 MutualTlsSecurityScheme

Certificate-based mutual TLS authentication.

```protobuf
message MutualTlsSecurityScheme {
  string description = 1;  // optional
}
```

No additional fields -- the mTLS handshake itself provides the authentication.

---

## 3. OAuth2 Flows (Section 4.5.7-4.5.10)

`OAuthFlows` is a **discriminated union** (`oneof`) supporting five flow types, two of which
are deprecated:

```protobuf
message OAuthFlows {
  oneof flow {
    AuthorizationCodeOAuthFlow authorization_code = 1;
    ClientCredentialsOAuthFlow client_credentials = 2;
    ImplicitOAuthFlow implicit = 3 [deprecated = true];   // use AuthCode + PKCE
    PasswordOAuthFlow password = 4 [deprecated = true];   // use AuthCode + PKCE or Device Code
    DeviceCodeOAuthFlow device_code = 5;
  }
}
```

### 3.1 AuthorizationCodeOAuthFlow

```protobuf
message AuthorizationCodeOAuthFlow {
  string authorization_url = 1 [(google.api.field_behavior) = REQUIRED];
  string token_url = 2 [(google.api.field_behavior) = REQUIRED];
  string refresh_url = 3;                                    // optional
  map<string, string> scopes = 4 [(google.api.field_behavior) = REQUIRED];
  bool pkce_required = 5;  // PKCE (RFC 7636) required for this flow
}
```

- `scopes` is a map of scope name to human-readable description.
- `pkce_required`: PKCE should always be used for public clients and is recommended for all.

### 3.2 ClientCredentialsOAuthFlow

Server-to-server authentication (no user interaction).

```protobuf
message ClientCredentialsOAuthFlow {
  string token_url = 1 [(google.api.field_behavior) = REQUIRED];
  string refresh_url = 2;                                    // optional
  map<string, string> scopes = 3 [(google.api.field_behavior) = REQUIRED];
}
```

### 3.3 DeviceCodeOAuthFlow

For input-constrained devices and CLI tools (RFC 8628).

```protobuf
message DeviceCodeOAuthFlow {
  string device_authorization_url = 1 [(google.api.field_behavior) = REQUIRED];
  string token_url = 2 [(google.api.field_behavior) = REQUIRED];
  string refresh_url = 3;                                    // optional
  map<string, string> scopes = 4 [(google.api.field_behavior) = REQUIRED];
}
```

### 3.4 Deprecated Flows

- **ImplicitOAuthFlow** -- deprecated, use Authorization Code + PKCE.
- **PasswordOAuthFlow** -- deprecated, use Authorization Code + PKCE or Device Code.

---

## 4. SecurityRequirements

```protobuf
message SecurityRequirement {
  // A map of security scheme names to the required scopes.
  map<string, StringList> schemes = 1;
}

message StringList {
  repeated string list = 1;
}
```

Each `SecurityRequirement` maps a **scheme name** (key in `AgentCard.securitySchemes`) to a
list of required scopes. For non-OAuth schemes, the scope list is typically empty.

Multiple `SecurityRequirement` entries in the `security` array represent **alternatives**
(logical OR) -- the client can satisfy any one of them. Within a single
`SecurityRequirement`, all listed schemes must be satisfied (logical AND).

---

## 5. Security Declaration in Agent Card

The Agent Card carries two security-related fields:

```protobuf
// From AgentCard message:
map<string, SecurityScheme> security_schemes = 8;
repeated SecurityRequirement security_requirements = 9;
```

### JSON representation

```json
{
  "name": "GeoSpatial Route Planner Agent",
  "version": "1.2.0",
  "supportedInterfaces": [
    {
      "url": "https://georoute-agent.example.com/a2a/v1",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    }
  ],
  "capabilities": {
    "streaming": true,
    "pushNotifications": true,
    "extendedAgentCard": true
  },
  "securitySchemes": {
    "google": {
      "openIdConnectSecurityScheme": {
        "openIdConnectUrl": "https://accounts.google.com/.well-known/openid-configuration"
      }
    }
  },
  "security": [
    { "google": ["openid", "profile", "email"] }
  ],
  "skills": [ ... ]
}
```

### How clients use it

1. Client fetches the public Agent Card (unauthenticated).
2. Client reads `securitySchemes` to understand available auth mechanisms.
3. Client reads `security` to determine which scheme(s) + scopes are required.
4. Client obtains credentials out-of-band (e.g., OAuth token exchange).
5. Client includes credentials in every subsequent A2A request.

---

## 6. Public vs. Protected Endpoints

### Public (no authentication required)

| Endpoint | Description |
|----------|-------------|
| `GET /.well-known/agent-card.json` | Public Agent Card discovery |

### Protected (authentication required)

| Operation | Method (JSON-RPC) | Description |
|-----------|-------------------|-------------|
| Send Message | `message/send` | Initiate agent interaction |
| Send Streaming Message | `message/stream` | Send with SSE streaming |
| Get Task | `tasks/get` | Retrieve task state |
| List Tasks | `tasks/list` | Query multiple tasks |
| Cancel Task | `tasks/cancel` | Request task cancellation |
| Subscribe to Task | `tasks/resubscribe` | Stream task updates (SSE) |
| Get Extended Agent Card | `agent/authenticatedExtendedCard` | Authenticated card with extra details |
| Create Push Notification Config | `pushNotification/set` | Register webhook |
| Get Push Notification Config | `pushNotification/get` | Retrieve webhook config |
| List Push Notification Configs | `pushNotification/list` | List all webhooks |
| Delete Push Notification Config | `pushNotification/delete` | Remove webhook |

---

## 7. Authentication and Authorization (Section 7)

### 7.1 Protocol Security

> Production deployments **MUST** use encrypted communication (HTTPS for HTTP-based
> bindings, TLS for gRPC). Implementations **SHOULD** use modern TLS configurations
> (TLS 1.3+ recommended) with strong cipher suites.

### 7.2 Server Identity Verification

> A2A Clients **SHOULD** verify the A2A Server's identity by validating its TLS
> certificate against trusted certificate authorities (CAs) during the TLS handshake.

### 7.3 Client Authentication Process

Three steps:

1. **Discovery of Requirements**: Client discovers the server's required authentication
   schemes via the `securitySchemes` field in the Agent Card.
2. **Credential Acquisition (Out-of-Band)**: Client obtains credentials through a process
   specific to the required scheme (e.g., OAuth token exchange, API key provisioning).
3. **Credential Transmission**: Client includes credentials in protocol-appropriate headers
   or metadata for **every** A2A request.

### 7.4 Server Authentication Responsibilities

The A2A Server:
- **MUST** authenticate every incoming request based on provided credentials and declared
  authentication requirements.
- **SHOULD** use appropriate binding-specific error codes for authentication challenges or
  rejections.
- **SHOULD** provide relevant authentication challenge information with error responses.

### 7.5 In-Task Authentication (Secondary Credentials)

If an agent requires additional credentials during task execution:

1. It **SHOULD** transition the task to the `TASK_STATE_AUTH_REQUIRED` state.
2. The accompanying `TaskStatus.update` **SHOULD** provide details about the required
   secondary authentication.
3. The client obtains credentials out-of-band and provides them in a subsequent message
   request (same `taskId` and `contextId`).

This enables scenarios where an agent needs user-specific credentials (e.g., access to a
third-party API on behalf of the user) that differ from the A2A protocol-level auth.

### 7.6 Authorization

Once authenticated, the server authorizes requests based on the authenticated identity and
its own policies. Authorization logic is implementation-specific and **MAY** consider:

- Specific skills requested
- Actions attempted within tasks
- Data access policies
- OAuth scopes (if applicable)

Key requirements:
- Servers **MUST** implement appropriate authorization scoping to ensure clients can only
  access authorized tasks.
- Servers **MUST** return only tasks visible to the authenticated client.
- Servers **MUST NOT** reveal the existence of resources the client is not authorized to
  access (prevents information leakage through error responses).

---

## 8. Extended Agent Card

The Extended Agent Card operation returns a more detailed Agent Card after client
authentication:

- **Availability**: Only if `AgentCard.capabilities.extendedAgentCard` is `true`.
- **Authentication**: Client **MUST** authenticate using one of the schemes declared in the
  public `AgentCard.securitySchemes` and `AgentCard.security` fields.
- **Response**: A complete `AgentCard` object with potentially additional skills,
  capabilities, or configuration not present in the public card.
- **Cache behavior**: Clients **SHOULD** replace their cached public Agent Card with the
  extended card for the duration of their authenticated session.
- **Access control**: Agents **MAY** return different details based on client authentication
  level.

Error codes:
- `UnsupportedOperationError` -- agent does not support extended cards.
- `ExtendedAgentCardNotConfiguredError` -- agent declares support but hasn't configured one.

---

## 9. Push Notification Authentication

Push notification webhooks include authentication credentials:

```protobuf
message AuthenticationInfo {
  // HTTP Authentication Scheme (e.g., "Bearer", "Basic", "Digest").
  // Case-insensitive per RFC 9110 Section 11.1.
  string scheme = 1 [(google.api.field_behavior) = REQUIRED];
  // Credentials (e.g., token for Bearer). Format depends on scheme.
  string credentials = 2;
}
```

When delivering push notifications, the agent:
- **MUST** include authentication credentials in request headers as specified in
  `PushNotificationConfig.authentication`.
- Uses standard HTTP `Authorization` header: `{scheme} {credentials}`.

```
POST {webhook_url}
Authorization: Bearer <token>
Content-Type: application/json
```

---

## 10. Agent Card Discovery

- **Well-Known URI**: `https://{server_domain}/.well-known/agent-card.json`
- This endpoint is **unauthenticated** -- returns the public Agent Card.
- The Agent Card declares the service endpoint URL, capabilities, security requirements,
  and skills.

---

## 11. Comparison with OpenAPI 3.2 Security

The A2A security model is explicitly based on OpenAPI 3.2 Security Scheme Objects. Key
differences:

| Aspect | OpenAPI 3.2 | A2A |
|--------|-------------|-----|
| Scope | Per-operation security | Per-agent security (all operations) |
| mTLS | Supported | Supported (dedicated scheme type) |
| Device Code flow | Not in OpenAPI | Added by A2A (RFC 8628) |
| PKCE flag | Not explicit | Explicit `pkce_required` field |
| Implicit/Password | Deprecated in 3.2 | Deprecated with explicit annotations |
| Security at operation level | Yes | No (agent-level only) |

---

## 12. Practical Implications for Gateway Implementation

### What the gateway needs to support

1. **Agent Card serving**: Serve `/.well-known/agent-card.json` without auth, include
   `securitySchemes` and `security` fields describing the gateway's auth requirements.

2. **SecurityScheme declaration**: At minimum, support declaring:
   - `HTTPAuthSecurityScheme` with `scheme: "Bearer"` for JWT/token auth
   - `APIKeySecurityScheme` for simple API key auth
   - `OAuth2SecurityScheme` with `ClientCredentialsOAuthFlow` for agent-to-agent auth

3. **Request authentication**: Validate credentials on every protected endpoint per the
   declared scheme(s).

4. **Authorization scoping**: Ensure task isolation -- clients can only access their own
   tasks. Never leak task existence to unauthorized clients.

5. **Extended Agent Card** (optional): If `capabilities.extendedAgentCard` is true, serve
   different card content based on authenticated identity.

6. **In-task auth state**: Support `TASK_STATE_AUTH_REQUIRED` state transition when
   downstream actors need additional credentials.

### Auth flow for agent-to-agent (server-to-server)

The most common pattern for automated agent-to-agent communication:

1. Remote agent fetches our public Agent Card.
2. Reads `securitySchemes` -- finds `oauth2` with `client_credentials` flow.
3. Exchanges client credentials at `token_url` for an access token.
4. Includes `Authorization: Bearer <token>` on all subsequent A2A requests.
5. Gateway validates the token, extracts scopes, and authorizes the request.

### Auth flow for human-facing clients (CLI, web)

1. Client fetches public Agent Card.
2. Reads `securitySchemes` -- finds `oauth2` with `authorization_code` flow.
3. Redirects user to `authorization_url` for consent.
4. Exchanges authorization code at `token_url` for access + refresh tokens.
5. Includes `Authorization: Bearer <token>` on all A2A requests.

---

## 13. JSON Examples

### Bearer Token Auth

```json
{
  "securitySchemes": {
    "bearerAuth": {
      "httpAuthSecurityScheme": {
        "scheme": "Bearer",
        "bearerFormat": "JWT"
      }
    }
  },
  "security": [
    { "bearerAuth": [] }
  ]
}
```

### API Key Auth

```json
{
  "securitySchemes": {
    "apiKey": {
      "apiKeySecurityScheme": {
        "name": "X-API-Key",
        "location": "header"
      }
    }
  },
  "security": [
    { "apiKey": [] }
  ]
}
```

### OAuth2 Client Credentials (agent-to-agent)

```json
{
  "securitySchemes": {
    "oauth2": {
      "oauth2SecurityScheme": {
        "flows": {
          "clientCredentials": {
            "tokenUrl": "https://auth.example.com/oauth/token",
            "scopes": {
              "tasks:read": "Read task state",
              "tasks:write": "Create and modify tasks"
            }
          }
        }
      }
    }
  },
  "security": [
    { "oauth2": ["tasks:read", "tasks:write"] }
  ]
}
```

### OpenID Connect (from spec example)

```json
{
  "securitySchemes": {
    "google": {
      "openIdConnectSecurityScheme": {
        "openIdConnectUrl": "https://accounts.google.com/.well-known/openid-configuration"
      }
    }
  },
  "security": [
    { "google": ["openid", "profile", "email"] }
  ]
}
```

### Multiple Schemes (alternatives)

```json
{
  "securitySchemes": {
    "bearerAuth": {
      "httpAuthSecurityScheme": {
        "scheme": "Bearer",
        "bearerFormat": "JWT"
      }
    },
    "apiKey": {
      "apiKeySecurityScheme": {
        "name": "X-API-Key",
        "location": "header"
      }
    }
  },
  "security": [
    { "bearerAuth": [] },
    { "apiKey": [] }
  ]
}
```

The two entries in `security` are alternatives (OR) -- the client can authenticate with
either Bearer token or API key.
