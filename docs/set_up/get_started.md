# Get Started

To begin using the [CGP client library](https://github.com/NHS-NGS/cgpclient), you'll need to follow these steps:

!!! gel-magnify "Register Your Application"

    To access the CGP APIs, you must first register an application on the NHS Developer Hub. 

    * **Production/Live Applications:** [NHS Developer Hub (Production)](https://digital.nhs.uk/developer)
    * **Development Applications:** [NHS Developer Hub (Development)](https://dos-internal.ptl.api.platform.nhs.uk/)

    Once logged in, navigate to **Environment access**. You'll land in **My applications and teams**. Click **Add new application**.

    When registering:
    
    * Choose the appropriate environment: `Development`, `Integration`, or `Production`.
    * Ensure this matches the `--api_host` parameter in your scripts.

!!! gel-magnify "Authenticate"

    The CGP client supports multiple authentication methods:

    * **API Key Authentication:**
        * Simple and straightforward, suitable for quick testing and development.
        * [Learn more about API Key Authentication :material-arrow-right:](key_auth.md)
    * **JWT Token Authentication (Recommended):**
        * Secure and robust, ideal for production environments.
        * Requires a private key and APIM key ID.
        * [Learn more about JWT Token Authentication :material-arrow-right:](jwt_auth.md)
    * **Sandbox Environment (No Authentication Required):**
        * For testing and experimentation in the APIM sandbox.
        * Useful for quickly exploring API functionality without setting up authentication.

!!! gel-magnify "Add Configuration"

    You can configure the CGP client library using a YAML configuration file, simplifying command-line usage. This file allows you to specify API host, API keys, private keys, and other settings. For more details on configuration options and file structure, please see the [configuration documentation](configuration.md).


--8<-- "includes/abbreviations.md"