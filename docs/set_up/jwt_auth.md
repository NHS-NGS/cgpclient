# JWT Authentication

JWT (JSON Web Token) authentication is the recommended, more secure method for accessing APIs hosted on the NHS APIM. This library supports both [API key authentication](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-api-key-authentication) and the more robust [signed JWT authentication pattern](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication).

**1. Register a Public Key and Associate with Your Application:**

To use signed JWT authentication, you'll need:

* An application and associated API key (as described in the API key authentication section).
* A registered public key with NHS APIM, associated with your application in the NHS Developer Hub.
* The "Genomic Data & Access Management" (GDAM) API associated with your application (select the API that mentions "signed JWT authentication").

For detailed setup instructions, refer to the official NHS [documentation](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication).

**2. Create Keys Using the `create_apim_keys.sh` Script:**

To simplify the process, we provide the `cgpclient/scripts/create_apim_keys.sh` bash script, which implements step 2 of the NHS guidance.

**Usage:**

```bash
bash cgpclient/scripts/create_apim_keys.sh -k "test-1" -d ~/apim_keys/
```

* `-k`: Specifies the Key Identifier (KID).
* `-d`: Specifies the directory where the keys will be stored (defaults to the current working directory).

**Important Security Note:** Keep your private key (`<KID>.pem`) secure and do not share it.

**3. Use the Private Key and KID in Scripts:**

The generated private key (<KID>.pem) and KID (e.g., "test-1") are required when creating signed JWTs using the scripts in this package.

**4. Verify JWT Authentication (Optional):**

To confirm your signed JWT authentication setup is working, use the `cgpclient/scripts/get_nhs_oauth_token.py` script to retrieve an OAuth token.

--8<-- "includes/abbreviations.md"