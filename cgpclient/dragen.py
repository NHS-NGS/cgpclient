import csv
import logging
import typing
from pathlib import Path

from fhir.resources.R4B.attachment import Attachment
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.composition import Composition, CompositionSection
from fhir.resources.R4B.documentreference import (
    DocumentReference,
    DocumentReferenceContent,
    DocumentReferenceContext,
    DocumentReferenceRelatesTo,
)
from fhir.resources.R4B.extension import Extension
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.servicerequest import ServiceRequest
from fhir.resources.R4B.specimen import Specimen, SpecimenCollection
from pydantic import BaseModel, PositiveInt

from cgpclient.drs import DrsObject
from cgpclient.drsupload import upload_file_with_drs
from cgpclient.fhir import (  # type: ignore
    CompositionStatus,
    DocumentReferenceDocStatus,
    DocumentReferenceRelationship,
    DocumentReferenceStatus,
    bundle_for,
    post_fhir_resource,
    reference_for,
)
from cgpclient.utils import create_uuid, get_current_datetime


class FastqListEntry(BaseModel):
    """A model for a row from a DRAGEN format FASTQ list CSV"""

    RGSM: str
    Read1File: Path
    RGID: str | None = None
    RGLB: str | None = None
    Lane: PositiveInt | None = None
    Read2File: Path | None = None


def read_fastq_list(
    fastq_list_csv: Path, fastq_list_sample_id: str | None = None
) -> list[FastqListEntry]:
    """Read a DRAGEN format FASTQ list CSV file"""
    entries: list[FastqListEntry] = []
    with open(fastq_list_csv, mode="r", encoding="utf8") as file:
        for row in csv.DictReader(file):
            entry: FastqListEntry = FastqListEntry.model_validate(row)
            if fastq_list_sample_id is None:
                logging.info("Using first RGSM found in file: %s", entry.RGSM)
                fastq_list_sample_id = entry.RGSM
            if entry.RGSM == fastq_list_sample_id:
                entries.append(entry)
            else:
                logging.info("Ignoring RGSM: %s", entry.RGSM)

    logging.info("Read %i entries from FASTQ list file", len(entries))
    return entries


@typing.no_type_check
def document_reference_for_drs_fastq(
    drs_object: DrsObject,
    specimen: Specimen,
    ods_code: str,
    pair_num: int | None = None,
) -> DocumentReference:
    """Create a DocumentReference resource for a DRS object pointing to a FASTQ file"""
    document_reference: DocumentReference = DocumentReference(
        id=create_uuid(),
        status=DocumentReferenceStatus.CURRENT,
        docStatus=DocumentReferenceDocStatus.FINAL,
        author=[
            Reference(
                identifier=Identifier(
                    system="https://fhir.nhs.uk/Id/ods-organization-code",
                    value=ods_code,
                )
            )
        ],
        subject=specimen.subject,
        type=CodeableConcept(
            coding=[
                Coding(
                    system="https://genomicsengland.co.uk/genomics-file-types",
                    code="FASTQ",
                )
            ]
        ),
        content=[
            DocumentReferenceContent(
                attachment=Attachment(
                    url=drs_object.self_uri,
                    contentType=drs_object.mime_type,
                    title=drs_object.name,
                    size=drs_object.size,
                    hash=drs_object.checksums[0].checksum,
                )
            ),
        ],
        context=DocumentReferenceContext(
            related=specimen.request + [reference_for(specimen)]
        ),
    )

    if pair_num is not None:
        document_reference.category = [
            CodeableConcept(
                coding=[
                    Coding(
                        system="https://genomicsengland.co.uk/genomic-file-types",
                        code=f"FASTQ-READ-GROUP-{pair_num}",
                    )
                ]
            )
        ]

    return document_reference


@typing.no_type_check
def fastq_list_entry_to_document_references(
    entry: FastqListEntry,
    specimen: Specimen,
    ods_code: str,
    api_base_url: str,
    headers: dict[str, str],
    dry_run: bool = False,
) -> list[DocumentReference]:
    """Create a list of DocumentReferences for each FASTQ in a read group"""
    # Upload FASTQs using DRS
    read1_drs_object: DrsObject = upload_file_with_drs(
        filename=entry.Read1File,
        api_base_url=api_base_url,
        headers=headers,
        dry_run=dry_run,
    )

    read1_doc_ref: DocumentReference = document_reference_for_drs_fastq(
        drs_object=read1_drs_object,
        specimen=specimen,
        ods_code=ods_code,
        pair_num=1 if entry.Read2File else None,
    )

    doc_refs: list[DocumentReference] = [read1_doc_ref]

    if entry.Read2File:
        # upload the second read group & relate it to the first
        read2_drs_object: DrsObject = upload_file_with_drs(
            filename=entry.Read2File,
            api_base_url=api_base_url,
            headers=headers,
            dry_run=dry_run,
        )

        read2_doc_ref: DocumentReference = document_reference_for_drs_fastq(
            drs_object=read2_drs_object,
            specimen=specimen,
            ods_code=ods_code,
            pair_num=2,
        )

        # add relationship between the paired FASTQs
        read2_doc_ref.relatesTo = [
            DocumentReferenceRelatesTo(
                code=DocumentReferenceRelationship.APPENDS,
                target=reference_for(read1_doc_ref),
            )
        ]

        read1_doc_ref.relatesTo = [
            DocumentReferenceRelatesTo(
                code=DocumentReferenceRelationship.APPENDS,
                target=reference_for(read2_doc_ref),
            )
        ]

        doc_refs.append(read2_doc_ref)

    return doc_refs


@typing.no_type_check
def map_entries_to_fhir_bundle(
    entries: list[FastqListEntry],
    ngis_participant_id: str,
    ngis_referral_id: str,
    ods_code: str,
    api_base_url: str,
    tumour_id: str | None = None,
    headers: dict[str, str] | None = None,
    dry_run: bool = False,
) -> Bundle:
    """Create a FHIR transaction Bundle for the entries from the FASTQ list CSV"""
    patient_reference: Reference = Reference(
        identifier=Identifier(
            system="https://genomicsengland.co.uk/ngis-participant-id",
            value=ngis_participant_id,
        ),
        type=Patient.__name__,
    )

    referral_reference: Reference = Reference(
        identifier=Identifier(
            system="https://genomicsengland.co.uk/ngis-referral-id",
            value=ngis_referral_id,
        ),
        type=ServiceRequest.__name__,
    )

    specimen: Specimen = Specimen(
        id=create_uuid(),
        identifier=[
            Identifier(
                system=f"https://{ods_code}.nhs.uk/lab-sample-id", value=entries[0].RGSM
            )
        ],
        subject=patient_reference,
        request=[referral_reference],
        collection=SpecimenCollection(
            collector=Reference(
                identifier=Identifier(
                    system="https://fhir.nhs.uk/Id/ods-organization-code",
                    value=ods_code,
                )
            )
        ),
    )

    if tumour_id is None:
        logging.info("Creating Specimen resource for germline blood sample")
        specimen.extension = (
            Extension(
                url="https://fhir.hl7.org.uk/StructureDefinition/Extension-UKCore-SampleCategory",  # noqa: E501
                valueCodeableConcept=CodeableConcept(
                    coding=[
                        Coding(
                            system="https://fhir.hl7.org.uk/CodeSystem/UKCore-SampleCategory",  # noqa: E501
                            code="germline",
                            display="Germline",
                        )
                    ]
                ),
            ),
        )

        specimen.type = CodeableConcept(
            coding=[
                Coding(
                    system="http://snomed.info/sct",
                    code="445295009",
                    display="Blood specimen with EDTA",
                )
            ]
        )

    else:
        logging.info("Creating Specimen resource for tumour sample")
        specimen.extension = (
            Extension(
                url="https://fhir.hl7.org.uk/StructureDefinition/Extension-UKCore-SampleCategory",  # noqa: E501
                valueCodeableConcept=CodeableConcept(
                    coding=[
                        Coding(
                            system="https://fhir.hl7.org.uk/CodeSystem/UKCore-SampleCategory",  # noqa: E501
                            code="solid-tumour",
                            display="Solid Tumour",
                        )
                    ]
                ),
            ),
        )

        specimen.identifier += [
            Identifier(system=f"https://{ods_code}.nhs.uk/tumour-id", value=tumour_id)
        ]

    document_references: list[DocumentReference] = []

    for entry in entries:
        document_references.extend(
            fastq_list_entry_to_document_references(
                entry=entry,
                specimen=specimen,
                ods_code=ods_code,
                api_base_url=api_base_url,
                headers=headers,
                dry_run=dry_run,
            )
        )

    composition: Composition = Composition(
        id=create_uuid(),
        status=CompositionStatus.FINAL,
        type=CodeableConcept(
            coding=[Coding(system="http://loinc.org", code="86206-0")]
        ),
        date=get_current_datetime(),
        author=[
            Reference(
                identifier=Identifier(
                    system="https://fhir.nhs.uk/Id/ods-organization-code",
                    value=ods_code,
                ),
            )
        ],
        title="WGS FASTQ sample delivery",
        section=[
            CompositionSection(title="sample", entry=[reference_for(specimen)]),
            CompositionSection(
                title="fastqs",
                entry=[
                    reference_for(document_reference)
                    for document_reference in document_references
                ],
            ),
        ],
    )

    return bundle_for([composition, specimen] + document_references)


def upload_sample_from_fastq_list(
    fastq_list_csv: Path,
    ngis_participant_id: str,
    ngis_referral_id: str,
    ods_code: str,
    api_base_url: str,
    tumour_id: str | None = None,
    headers: dict[str, str] | None = None,
    fastq_list_sample_id: str | None = None,
    dry_run: bool = False,
) -> None:
    """Convert a FASTQ list CVS into DRS objects and FHIR resources, and upload
    the FASTQs and the DRS and FHIR resources to the relevant services
    """
    entries: list[FastqListEntry] = read_fastq_list(
        fastq_list_csv=fastq_list_csv, fastq_list_sample_id=fastq_list_sample_id
    )

    fhir_bundle: Bundle = map_entries_to_fhir_bundle(
        entries=entries,
        ngis_participant_id=ngis_participant_id,
        ngis_referral_id=ngis_referral_id,
        ods_code=ods_code,
        tumour_id=tumour_id,
        api_base_url=api_base_url,
        headers=headers,
        dry_run=dry_run,
    )

    post_fhir_resource(
        resource=fhir_bundle,  # type: ignore
        api_base_url=api_base_url,
        ods_code=ods_code,
        headers=headers,
        dry_run=dry_run,
    )
