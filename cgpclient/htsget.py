def htsget_base_url(api_base_url: str) -> str:
    return f"https://{api_base_url}/ga4gh/htsget/v1.3"


def mime_type_to_htsget_endpoint(mime_type: str) -> str | None:
    mapping: dict[str, str] = {
        "application/cram": "reads",
        "application/bam": "reads",
        "text/vcf": "variants",
    }

    return mapping.get(mime_type, None)
