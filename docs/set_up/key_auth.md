# API Key Authentication

API key authentication is a straightforward method for accessing the CGP APIs. To use it, you'll need to register your application and add the required API within the NHS Developer Hub.

**1. Add the Genomic Data & Access Management (GDAM) API:**

* Navigate to your application within the appropriate environment (Development or Production) on the NHS Developer Hub.
* Search for and add the "Genomic Data & Access Management" (GDAM) API.
* **Important:** Select the GDAM API that explicitly mentions "API key authentication."
* **Development Applications:** API access is typically auto-approved.
* **Production Applications:** You'll need to complete the NHS onboarding process.

**2. Fetch an OAuth Token (Using the `get_nhs_oauth_token.py` script):**

For development, you can use the `cgpclient/scripts/get_nhs_oauth_token.py` script to fetch an OAuth token from the NHS APIM using signed JWT authentication. This script simplifies the process described in the [NHS documentation](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication).

**Usage:**

```bash
python cgpclient/scripts/get_nhs_oauth_token.py --help
```

Example:

```bash
PEM_FILE=path/to/test-1.pem
API_KEY=NHSAPIMAPIKEY
python cgpclient/scripts/get_nhs_oauth_token.py \
  --api_host internal-dev.api.service.nhs.uk \
  --api_key $API_KEY \
  --private_key_pem_file $PEM_FILE \
  --apim_kid test-1
```

**Note:** OAuth tokens expire after 10 minutes. You'll need to refresh them for long-running applications.

**3. Using the OAuth Token with curl:**

You can use the fetched OAuth token in curl commands to interact directly with the API.

Example:

```bash
PEM_FILE=path/to/test-1.pem
API_KEY=NHSAPIMAPIKEY
OAUTH_TOKEN=$(python cgpclient/scripts/get_nhs_oauth_token.py -pem $PEM_FILE -k $API_KEY -host internal-dev.api.service.nhs.uk -kid test-1)
curl "[https://internal-dev.api.service.nhs.uk/genomic-data-access/FHIR/R4/ServiceRequest?identifier=r30000000001](https://internal-dev.api.service.nhs.uk/genomic-data-access/FHIR/R4/ServiceRequest?identifier=r30000000001)" -H "Authorization: Bearer $OAUTH_TOKEN"
```

**4. Configuration File (Optional):**

If you use a configuration file at ~/.cgpclient/config.yaml with the necessary arguments, you can simplify the command:

```bash
OAUTH_TOKEN=$(python cgpclient/scripts/get_nhs_oauth_token.py)
```

**5. Choosing Authentication (API Key vs. JWT):**

* **Default:** The library defaults to JWT token authentication if both `--private_key_pem_file` and `--apim_kid` are provided.
* **API Key:** To use API key authentication, omit `--private_key_pem_file` and `--apim_kid`, and only provide `--api_key`.

--8<-- "includes/abbreviations.md"