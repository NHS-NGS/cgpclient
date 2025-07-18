# Visualising Genomic Data with IGV.js Workshop

## About This Workshop

This workshop teaches you how to use the CGPClient library to stream Whole Genome Sequencing (WGS) genomic data files from the Genomics Medicine Service (GMS) through the HTSGET protocol and visualize them with IGV.js.

**Learning Objectives**

By the end of this workshop, you will be able to:

- Set up authentication with the NHS API Platform (APIM)
- Use the CGPClient library to discover and access genomic data files
- Stream WGS genomic data (BAM, CRAM, VCF) via HTSGET protocol
- Integrate genomic data with IGV.js for visualization

**Key Technologies**

- **[HTSGET](https://samtools.github.io/hts-specs/htsget.html)**: A protocol for fast, indexed access to genomic data over HTTP. Instead of downloading entire files, it streams only specific genomic regions, dramatically reducing bandwidth and improving performance.
- **[IGV (Integrative Genomics Viewer)](https://igv.org/)**: The web-based version of the widely-used Integrative Genomics Viewer, enabling Clinical Scientists to quality check variants, examine read alignments, and make informed clinical decisions directly in the browser.

## Environment Setup

### 1. Clone and Set Up CGPClient

Clone the repository and navigate to the project directory:

```bash
git clone https://github.com/NHS-NGS/cgpclient
cd cgpclient
```

Create and activate a Python environment (using conda):

```bash
# Create and activate environment
conda create --name=cgpclient python=3.13
conda activate cgpclient
```

!!! gel-magnify "Environment Management"
    The environment only needs to be set up once and can be reused across multiple workshop sessions.

### 2. Install Dependencies

Install Poetry for dependency management:

```bash
pip install poetry
```

Install the client library and dependencies:

```bash
poetry install
```

### 3. Verify Installation

Test that everything is installed correctly:

```bash
python -c "import cgpclient; print('CGPClient installed successfully')"
```

If you encounter errors, ensure you're in the correct conda environment and that all dependencies were installed properly.


## Authentication Setup

The NHS API Platform uses JWT (JSON Web Token) authentication with API keys. You'll need to register your application and obtain three key pieces of information: API Key, Private Key PEM, and APIM KID.

!!! info "Authentication Reference"
    For detailed authentication methods and troubleshooting, see the [Authentication Guide](../set_up/auth.md)

### Step 1: Register in the NHS API Platform

1. Navigate to the NHS Developer Hub: [https://dos-internal.ptl.api.platform.nhs.uk/](https://dos-internal.ptl.api.platform.nhs.uk/)
2. **Log in** with your NHS.net email address or create an account

### Step 2: Create Your Application

1. Go to **Environment access** → **My applications and teams**
2. Click **Add new application**
3. Fill in your application details:
   - **Environment**: Select 'Development' (for this workshop)
   - **Owner**: Select 'Me'
   - **Name**: Choose a descriptive name (e.g., "test-igv-workshop")
4. Click **Create Application**

![Guide to create application in APIM](../assets/img/create_app_in_apim.jpg)

### Step 3: Connect the GDAM API

1. In your application dashboard, find the **Connected APIs** section
2. Click **Add APIs**
3. Search for "GDAM API" and select the version that explicitly mentions **API key authentication**
4. Click **Add** to connect the API to your application

You should now see the linked API in your application dashboard.

![Guide to connect API to the application](../assets/img/link_api_in_apim.png)

### Step 4: Generate Your API Key and Private Key

#### Get Your API Key (KID)
1. In your application dashboard, select **Active API keys**
2. Copy your **Key** - this is your KID (Key Identifier)

![Get KID](../assets/img/get_apim_key.png)

#### Generate Your Private Key
Use the CGPClient script to generate the required keys:

```bash
cgpclient/scripts/create_apim_keys.sh -k YOUR_API_KEY -d ~/.cgpclient/test-1.pem
```

Replace `YOUR_API_KEY` with the key you copied from the NHS Developer Hub.

**Expected output:**
```bash
Output directory '{private_key_pem}' does not exist. Creating it...
Generating RSA private key, 4096 bit long modulus (2 primes)
...
Key pair and JWKS JSON created successfully for KID: {YOUR_API_KEY} in directory: ~/.cgpclient/
```

### Step 5: Configure CGPClient

Create the configuration directory and file:

```bash
mkdir -p ~/.cgpclient
nano ~/.cgpclient/config.yaml
```

Add the following configuration (replace the placeholder values):

```yaml
api_host: internal-dev.api.service.nhs.uk 
api_name: genomic-data-access
api_key: YOUR_API_KEY_HERE  # API key from the NHS Developer Hub
private_key_pem: /absolute/path/to/test-1.pem # Path to your private key
apim_kid: test-1  # Key ID (KID) associated with the key pair
output_dir: /tmp/output  # Directory for output files
pretty_print: true  # Format output for readability
```

## Discovering Available Genomic Files


### Understanding the List Files Command

The `list_files` script queries the [Genomic Data Access and Management (GDAM) API](https://digital.nhs.uk/developer/api-catalogue/genomic-data-access-and-managementApi) to securely obtain file information through the [DocumentReference](https://digital.nhs.uk/developer/api-catalogue/genomic-data-access-and-management#get-/FHIR/R4/DocumentReference) endpoint.

### Basic File Discovery

List all files for a specific referral:

```bash
cgpclient/scripts/list_files --referral_id r30000000001
```

!!! info "Configuration File"
    This command uses your default configuration file at `~/.cgpclient/config.yaml`. If you used a different location, specify it with: `-cfg CONFIG_FILE` or `--config_file CONFIG_FILE`

### Filtering for Specific Files

To retrieve specific file types (e.g., CRAM files for a proband), use filtering options:

```bash
cgpclient/scripts/list_files \
--referral_id r30000000001 \
--participant_id p12345678301 \
--mime_type application/cram \
--include_drs_access_urls \
--pivot
```

**Command breakdown:**
- `--referral_id`: Filters to a specific referral (family/case)
- `--participant_id`: Filters to a specific participant within the referral
- `--mime_type`: Filters by file type (application/cram, application/vcf, etc.)
- `--include_drs_access_urls`: Includes HTSGET URLs for streaming
- `--pivot`: Formats output for easier reading

### Understanding the Output

The script returns detailed information about each genomic file:

```bash
file property   value
last_updated    2025-07-07T14:03:28
ngis_category   CRAM
content_type    application/cram
size            [file_size]
author_ods_code 8J834
referral_id     r30000000001
participant_id  p12345678301
sample_id       LP1000000-DNA_B05
run_id          [run_identifier]
name            LP1000000-DNA_B05.cram
s3_url          s3://mr459-dev-cgp-objects/2025/07/07/496fe8c9-d3bf-441f-b640-dd1ae3086e6b/LP1000000-DNA_B05.cram
htsget_url      https://sandbox.api.service.nhs.uk/genomic-data-access/ga4gh/htsget/v1.3/reads/1f271be3-7f3d-4cfa-8a1d-31f11a5f6427
```

**Key fields:**
- `name`: The original filename
- `s3_url`: Direct S3 location (for reference)
- `htsget_url`: The streaming URL we'll use with IGV.js
- `mime_type`: File format (CRAM, VCF, etc.)
- `size`: File size in bytes

## Streaming Data to IGV.js

## Streaming Data to IGV.js

With the HTSGET URL obtained from the file discovery step, you can now stream genomic data directly to IGV.js for visualization.

### Setting Up IGV.js

IGV.js can be integrated into web applications or used standalone. The HTSGET URL from the previous step allows IGV.js to stream only the genomic regions you're viewing, rather than downloading entire files.

### Understanding HTSGET Parameters

The HTSGET protocol allows you to specify genomic regions of interest by supplying parameters to the endpoint. When accessing reads data, you can limit the region using `referenceName`, `start`, and `end` parameters.

#### Direct HTSGET API Call Example

You can test the HTSGET endpoint directly using curl:

```bash
curl -v -H "apikey: {YOUR API KEY}" \
'{HTSGET URL}?referenceName=chr1&start=1234&end=4321'
```

**Parameters explained:**
- `referenceName=chr1`: Chromosome or contig name
- `start=1234`: Start position (0-based)
- `end=4321`: End position (exclusive)

This targeted approach means you only retrieve reads overlapping your region of interest, rather than the entire file.

#### Using HTSGET URLs in IGV.js

The `htsget_url` from your file discovery output can be used directly in IGV.js. IGV.js will automatically append the appropriate parameters when you navigate to different genomic regions:

```javascript
// Example IGV.js configuration
const options = {
    tracks: [
        {
            type: 'alignment',
            format: 'cram',
            name: 'LP1000000-DNA_B05',
            url: '{HTSGET URL}'
        }
    ]
};
```

WIP - This is currently causing an error.