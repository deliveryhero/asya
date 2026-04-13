# MCP Authorization Specification - Research Summary

**Sources**:
- [MCP Authorization Spec (2025-03-26)](https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization)
- [MCP Authorization Tutorial](https://modelcontextprotocol.io/docs/tutorials/security/authorization)

**Date**: 2026-03-06

---

## 1. Auth Mechanism: OAuth 2.1 with PKCE

MCP authorization is built on **OAuth 2.1** (IETF Draft) with mandatory PKCE for all clients.

Key standards referenced:
- [OAuth 2.1 IETF Draft](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-12)
- [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) - OAuth 2.0 Authorization Server Metadata
- [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591) - OAuth 2.0 Dynamic Client Registration
- [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) - Protected Resource Metadata

**Authorization is OPTIONAL** for MCP implementations. When supported:
- HTTP-based transports **SHOULD** conform to the spec
- STDIO transports **SHOULD NOT** use this spec (use environment-based credentials instead)
- Alternative transports **MUST** follow established security best practices for their protocol

### Supported Grant Types

MCP servers **SHOULD** support the grant types matching their intended audience:

1. **Authorization Code** (with PKCE) - when the client acts on behalf of a human end user (e.g., an agent calls an MCP tool implemented by a SaaS system)
2. **Client Credentials** - when the client is another application, not a human (e.g., an agent calls a secure MCP tool to check inventory)

### Implementation Requirements

- PKCE is **REQUIRED** for all clients (public and confidential)
- Token rotation **SHOULD** be implemented
- Token lifetimes **SHOULD** be limited
- All authorization endpoints **MUST** be served over HTTPS
- Redirect URIs **MUST** be either localhost URLs or HTTPS URLs

---

## 2. Authorization Flow

The complete flow proceeds in these steps:

### Step 1: Initial Request and 401 Challenge

When authorization is required and not yet proven, the server **MUST** respond with `HTTP 401 Unauthorized`:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer realm="mcp",
  resource_metadata="https://your-server.com/.well-known/oauth-protected-resource"
```

The `resource_metadata` parameter in the `WWW-Authenticate` header points the client to the Protected Resource Metadata (PRM) document.

### Step 2: Protected Resource Metadata Discovery (RFC 9728)

The client fetches the PRM document to learn about the authorization server, supported scopes, and other resource information:

```json
{
  "resource": "https://your-server.com/mcp",
  "authorization_servers": ["https://auth.your-server.com"],
  "scopes_supported": ["mcp:tools", "mcp:resources"]
}
```

### Step 3: Authorization Server Metadata Discovery (RFC 8414)

The client discovers the authorization server capabilities by fetching its metadata at the `.well-known` endpoint. If the PRM document lists multiple authorization servers, the client can choose which one to use.

```json
{
  "issuer": "https://auth.your-server.com",
  "authorization_endpoint": "https://auth.your-server.com/authorize",
  "token_endpoint": "https://auth.your-server.com/token",
  "registration_endpoint": "https://auth.your-server.com/register"
}
```

### Step 4: Dynamic Client Registration (optional)

If supported, the client registers itself:

```json
POST /register

{
  "client_name": "My MCP Client",
  "redirect_uris": ["http://localhost:3000/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"]
}
```

### Step 5: Authorization Code Exchange with PKCE

1. Client generates `code_verifier` and `code_challenge`
2. Client opens browser to `/authorize` with `code_challenge`
3. User authenticates and authorizes
4. Authorization server redirects back with authorization code
5. Client exchanges code + `code_verifier` for tokens

### Step 6: Token Response

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "def502...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

### Step 7: Authenticated Requests

```http
GET /mcp HTTP/1.1
Host: your-server.com
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
```

---

## 3. Server Metadata Discovery

### Discovery Protocol

- MCP clients **MUST** implement RFC 8414 discovery
- MCP servers **SHOULD** implement RFC 8414 discovery
- Servers that do not support discovery **MUST** support fallback URLs

### Discovery Request

```http
GET /.well-known/oauth-authorization-server HTTP/1.1
Host: api.example.com
MCP-Protocol-Version: 2024-11-05
```

Clients **SHOULD** include `MCP-Protocol-Version: <protocol-version>` header during discovery.

### Authorization Base URL

The authorization base URL is determined by **discarding any path component** from the MCP server URL.

| MCP Server URL | Authorization Base URL | Metadata Endpoint |
|---|---|---|
| `https://api.example.com/v1/mcp` | `https://api.example.com` | `https://api.example.com/.well-known/oauth-authorization-server` |

### Fallback Endpoints (when metadata discovery returns 404)

If discovery fails, clients **MUST** use these default paths relative to the authorization base URL:

| Endpoint | Default Path | Description |
|---|---|---|
| Authorization Endpoint | `/authorize` | Authorization requests |
| Token Endpoint | `/token` | Token exchange and refresh |
| Registration Endpoint | `/register` | Dynamic client registration |

Example for MCP server at `https://api.example.com/v1/mcp`:
- `https://api.example.com/authorize`
- `https://api.example.com/token`
- `https://api.example.com/register`

Clients **MUST** first attempt metadata discovery before falling back to defaults.

### Protected Resource Metadata (RFC 9728)

This is a newer addition (compared to just RFC 8414). The MCP server hosts a PRM document that tells the client which authorization server(s) to use:

```
GET /.well-known/oauth-protected-resource HTTP/1.1
```

The PRM URL is also communicated in the `WWW-Authenticate` header of the 401 response via the `resource_metadata` parameter.

---

## 4. Token Usage

### Bearer Token in Authorization Header

Access tokens **MUST** be sent via the `Authorization` request header (per OAuth 2.1 Section 5.1.1):

```http
GET /v1/contexts HTTP/1.1
Host: mcp.example.com
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### Critical Rules

- Authorization **MUST** be included in **every HTTP request** from client to server, even if they are part of the same logical session
- Access tokens **MUST NOT** be included in the URI query string
- Servers **MUST** validate access tokens per OAuth 2.1 Section 5.2
- Invalid or expired tokens **MUST** receive HTTP 401

### Token Validation Approaches

The spec does not mandate a specific validation method. Options include:
- **Token introspection** (e.g., via Keycloak introspection endpoint)
- **JWT signature verification** using standalone libraries
- **Audience (`aud`) validation** - verify the token was issued for this server

Example decoded JWT from the tutorial:

```json
{
  "exp": 1755540817,
  "iat": 1755540757,
  "iss": "http://localhost:8080/realms/master",
  "aud": "http://localhost:3000",
  "sub": "33ed6c6b-c6e0-4928-a161-f2f69c7a03b9",
  "typ": "Bearer",
  "azp": "7975a5b6-8b59-4a85-9cba-8faebdab8974",
  "scope": "mcp:tools"
}
```

---

## 5. Public vs Protected Endpoints

### Public Endpoints (no auth required)

These metadata endpoints are accessible without authentication:

| Endpoint | Purpose |
|---|---|
| `/.well-known/oauth-authorization-server` | Authorization server metadata (RFC 8414) |
| `/.well-known/oauth-protected-resource` | Protected resource metadata (RFC 9728) |
| `/authorize` | Authorization endpoint (browser-based) |
| `/token` | Token exchange endpoint |
| `/register` | Dynamic client registration |

### Protected Endpoints (Bearer token required)

All MCP protocol endpoints (tool calls, resource access, etc.) require a valid Bearer token when authorization is enabled:

| Endpoint | Purpose |
|---|---|
| `/mcp` (or server-specific path) | MCP Streamable HTTP endpoint |
| Any MCP JSON-RPC endpoint | All protocol operations |

### Error Codes

| Status Code | Description | Usage |
|---|---|---|
| 401 | Unauthorized | Authorization required or token invalid |
| 403 | Forbidden | Invalid scopes or insufficient permissions |
| 400 | Bad Request | Malformed authorization request |

---

## 6. Dynamic Client Registration (RFC 7591)

### Requirements

- MCP clients and servers **SHOULD** support Dynamic Client Registration
- This is crucial because clients cannot know all possible servers in advance
- It enables seamless connection to new servers without manual registration

### Registration Request

```http
POST /register HTTP/1.1
Content-Type: application/json

{
  "client_name": "My MCP Client",
  "redirect_uris": ["http://localhost:3000/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"]
}
```

### When DCR is Not Available

If the authorization server does not support DCR, the MCP client must either:

1. **Hardcode** a client ID (and optionally client secret) for that specific server
2. **Present a UI** to users allowing them to enter client credentials manually after registering an OAuth client through the server's configuration interface

---

## 7. Transport-Specific Auth Differences

### HTTP-based Transports (Streamable HTTP, SSE)

- **SHOULD** conform to the MCP authorization specification
- Use OAuth 2.1 with PKCE
- Bearer tokens in every HTTP request
- Full metadata discovery flow applies

### STDIO Transport

- **SHOULD NOT** use this specification
- Use environment-based credentials instead
- Can use credentials from third-party libraries embedded in the MCP server
- Runs locally, so has flexible options for acquiring credentials

### Key Distinction

The spec explicitly states: "OAuth flows are designed for HTTP-based transports where the MCP server is remotely-hosted and the client uses OAuth to establish that a user is authorized to access said remote server."

There is **no documented difference** between Streamable HTTP and SSE transports for auth purposes - they both follow the same OAuth 2.1 flow since both are HTTP-based.

---

## 8. Third-Party Authorization Flow

MCP servers **MAY** support delegated authorization through third-party authorization servers. In this flow, the MCP server acts as:
- An **OAuth client** to the third-party auth server
- An **OAuth authorization server** to the MCP client

### Flow Steps

1. MCP client initiates standard OAuth flow with MCP server
2. MCP server redirects user to third-party authorization server
3. User authorizes with third-party server
4. Third-party server redirects back to MCP server with authorization code
5. MCP server exchanges code for third-party access token
6. MCP server generates its own access token **bound to the third-party session**
7. MCP server completes original OAuth flow with MCP client

### Session Binding Requirements

MCP servers implementing third-party authorization **MUST**:
1. Maintain secure mapping between third-party tokens and issued MCP tokens
2. Validate third-party token status before honoring MCP tokens
3. Implement appropriate token lifecycle management
4. Handle third-party token expiration and renewal

### Security Considerations for Third-Party Auth

Servers **MUST**:
1. Validate all redirect URIs
2. Securely store third-party credentials
3. Implement appropriate session timeout handling
4. Consider security implications of token chaining
5. Implement proper error handling for third-party auth failures

---

## 9. Security Considerations Summary

1. Clients **MUST** securely store tokens following OAuth 2.0 best practices
2. Servers **SHOULD** enforce token expiration and rotation
3. All authorization endpoints **MUST** be served over HTTPS
4. Servers **MUST** validate redirect URIs to prevent open redirect vulnerabilities
5. Redirect URIs **MUST** be either localhost URLs or HTTPS URLs
6. PKCE **REQUIRED** for all clients (public and confidential)
7. Never embed client credentials directly in code - use environment variables or secret storage
8. Validate token audience (`aud`) claim to prevent token passthrough attacks

---

## 10. Best Practices from the Spec

1. **Local clients as Public OAuth 2.1 Clients**: Use PKCE, secure token storage, token refresh, proper expiration handling
2. **Always implement metadata discovery**: Reduces need for manual endpoint configuration or fallback defaults
3. **Always implement Dynamic Client Registration**: Removes need for users to obtain client IDs manually
4. **Audience validation**: Configure tokens with the intended MCP server URI as the audience and validate it server-side

---

## 11. Relevance to Asya Gateway

For an MCP gateway implementation, the key takeaways are:

- **401 challenge**: When auth is enabled, respond with `401 Unauthorized` and `WWW-Authenticate` header pointing to PRM
- **Metadata endpoints**: Serve `/.well-known/oauth-protected-resource` and optionally `/.well-known/oauth-authorization-server` (or delegate to a separate auth server like Keycloak)
- **Token validation**: Every MCP request must include `Authorization: Bearer <token>` and the server must validate it
- **Scopes**: Define MCP-specific scopes (e.g., `mcp:tools`, `mcp:resources`) for fine-grained access control
- **The MCP server does NOT need to be the authorization server** - it can delegate to Keycloak, Auth0, or any OAuth 2.1-compliant provider
- **Auth is optional** - the spec explicitly states it's optional, so it should be feature-flagged in the gateway
