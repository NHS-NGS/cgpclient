# Visualising Genomic Data with IGV.js Workshop

## About This Workshop
This workshop teaches you how to use the CGPClient library to stream Whole Genome Sequencing (WGS) genomic data files from the Genomics Medicine Service (GMS) through the HTSGET protocol.

**Learning Objectives**

By the end of this workshop, you will be able to:

- Set up authentication with the NHS API Platform (APIM)
- Use the CGPClient library to discover and access genomic data files
- Stream WGS genomic data (BAM, CRAM, VCF) via HTSGET protocol
- Integrate genomic data with IGV.js for visualization

**What is HTSGET?**

[HTSGET](https://samtools.github.io/hts-specs/htsget.html) is a protocol that enables fast, indexed access to genomic data. It supports BAM, CRAM and VCF files.

**Why Use IGV.js?**

[IGV (Integrative Genomics Viewer)](https://igv.org/) is widely used by Clinical Scientists for interactive visualization of genomic data, enabling them to quality check variants, examine read alignments and calls, and ultimately make informed clinical decisions.


## Environment Setup

### Install CGPClient

```bash
git clone https://github.com/NHS-NGS/cgpclient
```

For this, we're going to assume you use conda for managing python environments, substitute thi for your preferred tool.

```bash
conda create --name=cgpclient python=3.13
conda activate cgpclient
```

The environment only needs to be set up once and can be reused. We use poetry to manage dependencies etc., so if you have a fresh new environment from the command above you first need to install poetry:

```bash
pip install poetry
```

Once you have poetry installed in a suitable python environment, and if you are in the directory containing this README then the following command will install the client library and dependencies.

```bash
poetry install
```


## Part 1: Authentication Setup

### Step 1: Register in the NHS API Platform (APIM)

1. Navigate to the NHS Developer Hub: https://dos-internal.ptl.api.platform.nhs.uk/
2. **Log in** or create an account (NHS.net email may be required)
3. Go to **Environment access** → **My applications and teams**
4. Click **Add new application**
5. Fill in your application details and save

### Step 2: Add the GDAM API

1. In your application dashboard, find the **Connected APIs** section
2. Click **Add APIs**
3. Search for "GDAM API" 
4. Select the version that explicitly mentions **API key authentication**
5. Add the API to your application

### Step 3: Retrieve Authentication Credentials

You'll need three pieces of information:

- **API Key**: Your application's API key
- **Private Key PEM**: Your application's private key
- **APIM KID**: Key identifier for your application

To find these:
1. In your application dashboard, locate the **Active API keys** section
2. Click **Edit** to view your API key and secret
3. Note down these credentials securely

For detailed authentication methods, see the [Authentication Guide](../set_up/auth.md) or the official NHS documentation: https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication



