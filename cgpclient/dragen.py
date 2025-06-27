from __future__ import annotations

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
from fhir.resources.R4B.organization import Organization
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.procedure import Procedure, ProcedurePerformer
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.servicerequest import ServiceRequest
from fhir.resources.R4B.specimen import Specimen
from pydantic import BaseModel, PositiveInt

from cgpclient.drs import DrsObject
from cgpclient.drsupload import upload_file_with_drs
from cgpclient.fhir import (  # type: ignore
    CompositionStatus,
    DocumentReferenceDocStatus,
    DocumentReferenceRelationship,
    DocumentReferenceStatus,
    ProcedureStatus,
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


def resolve_path(fastq_list_csv: Path, fastq: Path):
    return (fastq_list_csv.parent / fastq).resolve()


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
                # resolve the FASTQ paths relative to the directory
                # containing the FASTQ list CSV (if necessary)
                entry.Read1File = resolve_path(
                    fastq_list_csv=fastq_list_csv, fastq=entry.Read1File
                )
                if entry.Read2File is not None:
                    entry.Read2File = resolve_path(
                        fastq_list_csv=fastq_list_csv, fastq=entry.Read2File
                    )

                # include this entry
                entries.append(entry)
            else:
                logging.debug("Ignoring RGSM: %s", entry.RGSM)

    logging.info("Read %i entries from FASTQ list file", len(entries))
    return entries


@typing.no_type_check
def document_reference_for_drs_object(
    drs_object: DrsObject,
    specimen: Specimen,
    procedure: Procedure,
    lab_reference: Reference,
) -> DocumentReference:
    """Create a DocumentReference resource for a DRS object"""
    document_reference: DocumentReference = DocumentReference(
        id=create_uuid(),
        identifier=[
            Identifier(
                system=f"https://{lab_reference.identifier.value}.nhs.uk/filename",
                value=drs_object.name,
            )
        ],
        status=DocumentReferenceStatus.CURRENT,
        docStatus=DocumentReferenceDocStatus.FINAL,
        author=[lab_reference],
        subject=specimen.subject,
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
            related=specimen.request
            + [reference_for(specimen), reference_for(procedure)]
        ),
    )

    return document_reference


@typing.no_type_check
def fastq_list_entry_to_document_references(
    entry: FastqListEntry,
    specimen: Specimen,
    procedure: Procedure,
    lab_reference: Reference,
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

    read1_doc_ref: DocumentReference = document_reference_for_drs_object(
        drs_object=read1_drs_object,
        specimen=specimen,
        procedure=procedure,
        lab_reference=lab_reference,
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

        read2_doc_ref: DocumentReference = document_reference_for_drs_object(
            drs_object=read2_drs_object,
            specimen=specimen,
            procedure=procedure,
            lab_reference=lab_reference,
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

        read1_doc_ref.category = [
            CodeableConcept(
                coding=[
                    Coding(
                        system="https://genomicsengland.co.uk/genomic-file-types",
                        code="FASTQ-READ-GROUP-1",
                    )
                ]
            )
        ]

        read2_doc_ref.category = [
            CodeableConcept(
                coding=[
                    Coding(
                        system="https://genomicsengland.co.uk/genomic-file-types",
                        code="FASTQ-READ-GROUP-2",
                    )
                ]
            )
        ]

        doc_refs.append(read2_doc_ref)

    return doc_refs


@typing.no_type_check
def map_entries_to_fhir_bundle(
    entries: list[FastqListEntry],
    ngis_participant_id: str,
    ngis_referral_id: str,
    run_id,
    ods_code: str,
    api_base_url: str,
    tumour_id: str | None = None,
    run_info_file: Path | None = None,
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

    lab_reference: Reference = Reference(
        identifier=Identifier(
            system="https://fhir.nhs.uk/Id/ods-organization-code",
            value=ods_code,
        ),
        type=Organization.__name__,
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
    )

    procedure: Procedure = Procedure(
        id=create_uuid(),
        identifier=[
            Identifier(
                system=f"https://{ods_code}.nhs.uk/sequencing-run-id", value=run_id
            )
        ],
        code=CodeableConcept(
            coding=[
                Coding(
                    code="461571000124105",
                    system="http://snomed.info/sct",
                    display="Whole genome sequencing",
                )
            ]
        ),
        subject=patient_reference,
        performer=[ProcedurePerformer(actor=lab_reference)],
        basedOn=[referral_reference],
        status=ProcedureStatus.COMPLETED,
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
                procedure=procedure,
                lab_reference=lab_reference,
                api_base_url=api_base_url,
                headers=headers,
                dry_run=dry_run,
            )
        )

    if run_info_file is not None:
        run_info_drs_object: DrsObject = upload_file_with_drs(
            filename=run_info_file,
            api_base_url=api_base_url,
            headers=headers,
            dry_run=dry_run,
        )

        document_references.append(
            document_reference_for_drs_object(
                drs_object=run_info_drs_object,
                specimen=specimen,
                procedure=procedure,
                lab_reference=lab_reference,
            )
        )

    composition: Composition = Composition(
        id=create_uuid(),
        status=CompositionStatus.FINAL,
        type=CodeableConcept(
            coding=[Coding(system="http://loinc.org", code="86206-0")]
        ),
        date=get_current_datetime(),
        author=[lab_reference],
        title="WGS sample delivery",
        section=[
            CompositionSection(title="sample", entry=[reference_for(specimen)]),
            CompositionSection(title="run", entry=[reference_for(procedure)]),
            CompositionSection(
                title="files",
                entry=[
                    reference_for(document_reference)
                    for document_reference in document_references
                ],
            ),
        ],
    )

    return bundle_for([composition, specimen, procedure] + document_references)


def upload_dragen_run(
    fastq_list_csv: Path,
    ngis_participant_id: str,
    ngis_referral_id: str,
    run_id: str,
    ods_code: str,
    api_base_url: str,
    tumour_id: str | None = None,
    headers: dict[str, str] | None = None,
    fastq_list_sample_id: str | None = None,
    run_info_file: Path | None = None,
    dry_run: bool = False,
) -> None:
    """Convert a FASTQ list CSV into DRS objects and FHIR resources, and upload
    the FASTQs and the DRS and FHIR resources to the relevant services
    """
    entries: list[FastqListEntry] = read_fastq_list(
        fastq_list_csv=fastq_list_csv, fastq_list_sample_id=fastq_list_sample_id
    )

    fhir_bundle: Bundle = map_entries_to_fhir_bundle(
        entries=entries,
        ngis_participant_id=ngis_participant_id,
        ngis_referral_id=ngis_referral_id,
        run_id=run_id,
        run_info_file=run_info_file,
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
