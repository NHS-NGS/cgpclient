def htsget_base_url(api_base_url: str) -> str:
    return f"https://{api_base_url}/ga4gh/htsget/v1.3"


def mime_type_to_htsget_endpoint(mime_type: str) -> str:
    mapping: dict[str, str] = {
        "application/cram": "reads",
        "application/bam": "reads",
        "text/vcf": "variants",
    }

    if mime_type not in mapping:
        raise ValueError(f"Invalid mime type for htsget: {mime_type}")

    return mapping[mime_type]
