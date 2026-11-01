# Intermediate CA certificates for regulator downloads

Some publishers' servers do not send their intermediate certificate, so TLS verification fails
outside browsers (on Linux and in CI). The missing intermediates live here and are added to the
standard root bundle - verification still ends at a trusted root; nothing is skipped.

| File | Needed by | Issuer (root, already trusted) | Valid until | SHA-256 fingerprint |
|---|---|---|---|---|
| `globalsign-gcc-r46-ov-tls-ca-2025.pem` | www.ocs.go.th (PDPA 2562) | GlobalSign Root R46 | 2029-06-23 | `D1:60:E2:DE:4E:56:CB:10:B6:6C:1C:B0:AD:CB:79:CF:93:C7:8D:CD:9D:B3:0C:20:18:22:02:62:C0:40:63:F9` |

Source: the "CA Issuers" URL in the server certificate
(`http://secure.globalsign.com/cacert/gsgccr46ovtlsca2025.crt`), converted to PEM.

Adding one: download the URL from the server certificate's Authority Information Access field,
then confirm it chains to a trusted root and that the server certificate verifies with it:

```bash
openssl verify -CAfile "$(python -c 'import certifi;print(certifi.where())')" new.pem
openssl verify -CAfile "$(python -c 'import certifi;print(certifi.where())')" -untrusted new.pem server.pem
```

Never put a *root* or a self-signed certificate here, and never disable verification instead.
