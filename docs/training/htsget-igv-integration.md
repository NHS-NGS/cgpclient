# Visualising Genomic Data with IGV.js Workshop

## Learning Objectives

By the end of this workshop, you will be able to:

- Set up authentication with the NHS API Platform (APIM)
- Use the CGPClient library to discover and access genomic data files
- Stream WGS genomic data (BAM, CRAM, VCF) via HTSGET protocol
- Integrate genomic data with IGV.js for visualization

## About This Workshop

This workshop teaches you how to use the CGPClient library to stream Whole Genome Sequencing (WGS) genomic data files from the Genomics Medicine Service (GMS) through the HTSGET protocol.

**What is HTSGET?**

[HTSGET](https://samtools.github.io/hts-specs/htsget.html) is a protocol that enables fast, indexed access to genomic data. It supports BAM, CRAM and VCF files.

**Why Use IGV.js?**

[IGV (Integrative Genomics Viewer)](https://igv.org/) is widely used by Clinical Scientists for interactive visualization of genomic data, enabling them to quality check variants, examine read alignments and calls, and ultimately make informed clinical decisions.

--------------------

## Environment Setup

Before starting, we need to ensure our environment is set up correctly. To find more information on this, see the complete [Environment Setup](../set_up/set_up.md).

### Register in the APIM

To use the CGP APIs, you must first register your application on the NHS Developer Hub. For this workshop we're doing so in the Development sid.

Go to https://dos-internal.ptl.api.platform.nhs.uk/
**Log in** to the appropriate NHS Developer Hub. Create an account if needed (does it need to be nhs.net?)
Navigate to **Environment access** → **My applications and teams**.
Click **Add new application**.

### Authenticate

In our case, to authenticate, we'll use the API Key Authentication, but if you want to read of other ways, find more info [here](../set_up/auth.md)

Before fetching the token, navigate to the application you have created in the NHS develop hub, on the Connected APIs section, click on 'Add APIs'

Add screenshots

Search for the GDAM API and select the one that explicity mentions 'API key' authentication.

Add screenshots

For the next step we need the following information:

- api key
- private key pem
- apim kid

Within your application, click on 'edit' in the Active API keys section, there you will be able to see the apy key, as well as the secret.

https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication


## Part 1

For this demonstration, we're going to be using 

```bash
API_KEY=NHSAPIMAPIKEY
cgpclient/scripts/list_files \
--referral_id r30000000001 \
--api_host sandbox.api.service.nhs.uk \
--api_name genomic-data-access \
--api_key $API_KEY
```

The script prints details of each genomic file found, example output:

```bash
last_updated         content_type         size  author_ods_code    referral_id    participant_id    sample_id           run_id               name
2025-07-07T10:52:13  text/fastq              2  ODS123             r12345         p12345            glh_sample_id_1234  glh_run_folder_1234  2506905-D09_L01_R2_001.fastq.ora
2025-07-07T10:52:13  application/xml         9  ODS123             r12345         p12345            glh_sample_id_1234  glh_run_folder_1234  RunInfo.xml
2025-07-07T10:52:13  text/fastq              2  ODS123             r12345         p12345            glh_sample_id_1234  glh_run_folder_1234  2506905-D09_L01_R1_001.fastq.ora
...






## Environment Setup

### System Requirements

Ensure you have the following installed:
- Python 3.7 or higher
- pip package manager
- Git (for cloning repositories)

### Install CGPClient

```bash
pip install cgpclient
```

Or install from source:
```bash
git clone https://github.com/cgp-genomics/cgpclient.git
cd cgpclient
pip install -e .
```

For complete environment setup instructions, see [Environment Setup](../set_up/set_up.md).

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

## Part 2: Discovering Available Genomic Files

### Using the CGPClient to List Files

Now we'll use the CGPClient to discover what genomic files are available for a specific referral.

```bash
# Set your API key as an environment variable
export API_KEY=YOUR_NHSAPI_KEY_HERE

# List files for a specific referral
cgpclient/scripts/list_files \
--referral_id r30000000001 \
--api_host sandbox.api.service.nhs.uk \
--api_name genomic-data-access \
--api_key $API_KEY
```

### Understanding the Output

The script returns detailed information about each genomic file:

```bash
last_updated         content_type         size  author_ods_code    referral_id    participant_id    sample_id           run_id               name
2025-07-07T10:52:13  text/fastq              2  ODS123             r12345         p12345            glh_sample_id_1234  glh_run_folder_1234  2506905-D09_L01_R2_001.fastq.ora
2025-07-07T10:52:13  application/xml         9  ODS123             r12345         p12345            glh_sample_id_1234  glh_run_folder_1234  RunInfo.xml
2025-07-07T10:52:13  text/fastq              2  ODS123             r12345         p12345            glh_sample_id_1234  glh_run_folder_1234  2506905-D09_L01_R1_001.fastq.ora
```

**Key fields explained:**
- **content_type**: The file format (e.g., application/cram, text/vcf)
- **referral_id**: The clinical referral identifier
- **participant_id**: The patient identifier
- **sample_id**: The biological sample identifier
- **name**: The actual filename

### Filtering for Visualization-Ready Files

Look for files with these content types:
- `application/cram`: Alignment files suitable for IGV
- `text/vcf` or `application/vcf`: Variant files
- `application/bam`: Binary alignment files

## Part 3: Streaming Data to IGV.js

### Setting up HTSGET Access

Once you've identified the files you want to visualize, you can stream them directly to IGV.js using HTSGET URLs.

```bash
# Get HTSGET URL for a specific file
cgpclient/scripts/get_htsget_url \
--file_id FILE_ID_FROM_LISTING \
--api_host sandbox.api.service.nhs.uk \
--api_name genomic-data-access \
--api_key $API_KEY
```

### Integrating with IGV.js

Here's a basic example of loading the data into IGV.js:

```javascript
// Initialize IGV
const igvDiv = document.getElementById('igv-div');
const options = {
    genome: 'hg38',  // or hg19, depending on your data
    tracks: [
        {
            name: 'Patient Alignments',
            type: 'alignment',
            format: 'cram',
            url: 'YOUR_HTSGET_CRAM_URL_HERE',
            indexURL: 'YOUR_HTSGET_CRAM_INDEX_URL_HERE'
        },
        {
            name: 'Patient Variants',
            type: 'variant',
            format: 'vcf',
            url: 'YOUR_HTSGET_VCF_URL_HERE',
            indexURL: 'YOUR_HTSGET_VCF_INDEX_URL_HERE'
        }
    ]
};

igv.createBrowser(igvDiv, options);
```

### Navigation Tips

- Use the search box to jump to specific genes or genomic coordinates
- Right-click on variants to see detailed information
- Use the zoom controls to examine read-level details
- Toggle tracks on/off using the track controls

## Part 4: Quality Assessment and Clinical Interpretation

### What to Look For

When examining variants in IGV.js:

1. **Read Depth**: Sufficient coverage (typically >20x for clinical variants)
2. **Allele Balance**: Roughly 50% for heterozygous variants
3. **Read Quality**: High-quality reads supporting the variant
4. **Strand Bias**: Variant supported by reads from both strands
5. **Mapping Quality**: Reads map uniquely to the reference genome

### Common Quality Issues

- **Low coverage**: Insufficient reads to confidently call variants
- **Strand bias**: Variant only supported by reads from one strand
- **Repetitive regions**: Alignment artifacts in repetitive sequences
- **Sequencing errors**: Random errors vs. true variants

## Troubleshooting

### Common Issues

**Authentication errors:**
- Verify your API key is correct
- Check that the GDAM API is added to your application
- Ensure you're using the correct API host

**No files found:**
- Verify the referral ID exists in the system
- Check your permissions for the referral
- Ensure you're querying the correct environment (sandbox vs. production)

**IGV.js loading issues:**
- Verify HTSGET URLs are accessible
- Check that index files are available
- Ensure proper CORS headers are set

### Getting Help

- Check the [CGPClient documentation](link-to-docs)
- Review the [NHS API Platform guides](https://digital.nhs.uk/developer)
- Contact the Genomics team for clinical questions

## Next Steps

After completing this workshop, you might want to:
- Explore advanced IGV.js features (custom tracks, annotations)
- Integrate with other NHS APIs for comprehensive clinical workflows
- Develop custom applications using the CGPClient library
- Learn about genomic data interpretation and clinical reporting

## Additional Resources

- [HTSGET Protocol Specification](https://samtools.github.io/hts-specs/htsget.html)
- [IGV.js Documentation](https://github.com/igvteam/igv.js/)
- [NHS API Platform Documentation](https://digital.nhs.uk/developer)
- [Genomics England Data Access](https://www.genomicsengland.co.uk/research/access-our-data)

## Glossary

- **BAM**: Binary Alignment Map - compressed binary format for storing sequence alignment data
- **CRAM**: Compressed Reference-oriented Alignment Map - more compressed alternative to BAM
- **VCF**: Variant Call Format - standard format for storing genetic variants
- **HTSGET**: Protocol for streaming genomic data over HTTP
- **IGV**: Integrative Genomics Viewer - tool for visualizing genomic data
- **APIM**: API Management platform used by NHS
- **CGPClient**: Python library for accessing Cancer Genome Project data
