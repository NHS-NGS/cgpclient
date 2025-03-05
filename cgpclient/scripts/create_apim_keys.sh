#!/bin/bash

# Based on this NHS guide:
# https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication
#
# This script implements Step 2 from the guide, once you have successfully run this script
# you can proceed with Step 3. Remember to keep your private key secret and don't share it
# with anyone.
#
# The private key <KID>.pem is the file you should provide when creating signed JWTs using the
# scripts in this package

usage() {
    echo "Usage: $0 -k <KID> [-d <output_directory>]"
    echo "  -k <KID>            Set the Key Identifer (KID) for the key generation and JWKS output"
    echo "  -d <OUTPUT_DIR>     Optional: Specify the output directory for generated files"
    exit 1
}

# Default output directory is the current directory
OUTPUT_DIR="."

# Parse command line arguments
while getopts "k:d:" opt; do
    case "$opt" in
        k) KID="$OPTARG" ;;
        d) OUTPUT_DIR="$OPTARG" ;;
        *) usage ;;
    esac
done

# Check if KID is set
if [ -z "$KID" ]; then
    echo "Error: KID is required."
    usage
fi

# Create the output directory if it doesn't exist
if [ ! -d "$OUTPUT_DIR" ]; then
    echo "Output directory '$OUTPUT_DIR' does not exist. Creating it..."
    mkdir -p "$OUTPUT_DIR"
fi

# Generate RSA private key
openssl genrsa -out "$OUTPUT_DIR/$KID.pem" 4096

# Generate the public key
openssl rsa -in "$OUTPUT_DIR/$KID.pem" -pubout -outform PEM -out "$OUTPUT_DIR/$KID.pem.pub"

# Extract the modulus from the private key for the JWKS output
MODULUS=$(
    openssl rsa -pubin -in $OUTPUT_DIR/$KID.pem.pub -noout -modulus `# Print modulus of public key` \
    | cut -d '=' -f2                                                `# Extract modulus value from output` \
    | xxd -r -p                                                     `# Convert from string to bytes` \
    | openssl base64 -A                                             `# Base64 encode without wrapping lines` \
    | sed 's|+|-|g; s|/|_|g; s|=||g'                                `# URL encode as JWK standard requires`
)

# Create the JWKS JSON file
echo '{
  "keys": [
    {
      "kty": "RSA",
      "n": "'"$MODULUS"'",
      "e": "AQAB",
      "alg": "RS512",
      "kid": "'"$KID"'",
      "use": "sig"
    }
  ]
}' > "$OUTPUT_DIR/$KID.json"

echo "Key pair and JWKS JSON created successfully for KID: $KID in directory: $OUTPUT_DIR"
