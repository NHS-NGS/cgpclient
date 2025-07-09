# Authenticate

The CGP client supports multiple authentication methods:

## API Key Authentication

!!! gel-attention ""

    **Simple and straightforward, suitable for quick testing and development.**

!!! gel-magnify ""

    === "1. Register"

        ### Register an application in the NHS Developer Hub

        1. First, follow the guidelince to [register your application](register.md)
        2. Navigate to your application within the appropriate environment (Development or Production) on the NHS Developer Hub.
        3. Search for and add the "Genomic Data & Access Management" (GDAM) API.

        !!! gel-question "Note"

            * **Important:** Select the GDAM API that explicitly mentions "API key authentication."

            * **Development Applications:** API access is typically auto-approved.

            * **Production Applications:** You'll need to complete the NHS onboarding process.

    === "2. Fetch an OAuth Token "

        ### Fetch an OAuth Token (Using the `get_nhs_oauth_token` script)

        For development, you can use the `cgpclient/scripts/get_nhs_oauth_token` script to fetch an OAuth token from the NHS APIM using signed JWT authentication. This script simplifies the process described in the [NHS documentation](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication).

        **Usage:**

        ```bash
        cgpclient/scripts/get_nhs_oauth_token --help
        ```

        Example:
        ```bash
        PEM_FILE=path/to/test-1.pem
        API_KEY=NHSAPIMAPIKEY
        cgpclient/scripts/get_nhs_oauth_token \
        --api_host internal-dev.api.service.nhs.uk \
        --api_key $API_KEY \
        --private_key_pem $PEM_FILE \
        --apim_kid test-1
        ```

        !!! gel-question "Note"

            OAuth tokens expire after 10 minutes. You'll need to refresh them for long-running applications.


    === "3. Using the OAuth Token"

        ### Using the OAuth Token with curl

        You can use the fetched OAuth token in curl commands to interact directly with the API.

        Example:

        ```bash
        PEM_FILE=path/to/test-1.pem
        API_KEY=NHSAPIMAPIKEY
        OAUTH_TOKEN=$(cgpclient/scripts/get_nhs_oauth_token -pem $PEM_FILE -k $API_KEY -host internal-dev.api.service.nhs.uk -kid test-1)
        curl "[https://internal-dev.api.service.nhs.uk/genomic-data-access/FHIR/R4/ServiceRequest?identifier=r30000000001](https://internal-dev.api.service.nhs.uk/genomic-data-access/FHIR/R4/ServiceRequest?identifier=r30000000001)" -H "Authorization: Bearer $OAUTH_TOKEN"
        ```

    === "4. Config File (Optional)"

        ### Configuration File (Optional)

        If you use a configuration file at ~/.cgpclient/config.yaml with the necessary arguments, you can simplify the command:

        ```bash
        OAUTH_TOKEN=$(cgpclient/scripts/get_nhs_oauth_token)
        ```

        **Choosing Authentication (API Key vs. JWT):**

        * **Default:** The library defaults to JWT token authentication if both `--private_key_pem` and `--apim_kid` are provided.
        * **API Key:** To use API key authentication, omit `--private_key_pem` and `--apim_kid`, and only provide `--api_key`.

------

## JWT Token Authentication (Recommended)

!!! gel-attention ""

    **Secure and robust, ideal for production environments. Requires a private key and APIM key ID.**

!!! gel-magnify ""

    === "1. Register"

        ### Register a Public Key and Associate with Your Application

        To use signed JWT authentication, you'll need:

        * An application and associated API key (as described in the API key authentication section).
        * A registered public key with NHS APIM, associated with your application in the NHS Developer Hub.
        * The "Genomic Data & Access Management" (GDAM) API associated with your application (select the API that mentions "signed JWT authentication").

        For detailed setup instructions, refer to the official NHS [documentation](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication).

    === "2. Create Keys"

        ### Create Keys Using the `create_apim_keys.sh` Script

        To simplify the process, we provide the `cgpclient/scripts/create_apim_keys.sh` bash script, which implements step 2 of the NHS guidance.

        **Usage:**

        ```bash
        bash cgpclient/scripts/create_apim_keys.sh -k "test-1" -d ~/apim_keys/
        ```

        * `-k`: Specifies the Key Identifier (KID).
        * `-d`: Specifies the directory where the keys will be stored (defaults to the current working directory).

        **Important Security Note:** Keep your private key (`<KID>.pem`) secure and do not share it.

    === "3. Use the Private Key and KID"

        ### Use the Private Key and KID in Scripts

        The generated private key (<KID>.pem) and KID (e.g., "test-1") are required when creating signed JWTs using the scripts in this package.

    === "4. Verify JWT Authentication"

        ### Verify JWT Authentication (Optional)

        To confirm your signed JWT authentication setup is working, use the `cgpclient/scripts/get_nhs_oauth_token` script to retrieve an OAuth token.

## Sandbox Environment

This methodology does not require authentication

!!! gel-attention ""

    * **For testing and experimentation in the APIM sandbox.**
    * **Useful for quickly exploring API functionality without setting up authentication.**