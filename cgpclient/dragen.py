import csv
import logging
import typing
from pathlib import Path

from fhir.resources.R4B.attachment import Attachment
from fhir.resources.R4B.bundle import Bundle, BundleEntry, BundleEntryRequest
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.documentreference import (
    DocumentReference,
    DocumentReferenceContent,
    DocumentReferenceContext,
    DocumentReferenceRelatesTo,
)
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.reference import Reference
from fhir.resources.R4B.servicerequest import ServiceRequest
from fhir.resources.R4B.specimen import Specimen, SpecimenCollection
from pydantic import BaseModel, PositiveInt

from cgpclient.drs import DrsObject
from cgpclient.drsupload import upload_file_with_drs
from cgpclient.fhir import (  # type: ignore
    BundleRequestMethod,
    BundleType,
    DocumentReferenceDocStatus,
    DocumentReferenceRelationship,
    DocumentReferenceStatus,
    post_fhir_resource,
    reference_for,
)
from cgpclient.utils import create_uuid


class DragenFastqListEntry(BaseModel):
    RGSM: str
    Read1File: Path
    RGID: str | None = None
    RGLB: str | None = None
    Lane: PositiveInt | None = None
    Read2File: Path | None = None


def read_dragen_fastq_list(
    fastq_list_csv: Path, fastq_list_sample_id: str | None = None
) -> list[DragenFastqListEntry]:
    entries: list[DragenFastqListEntry] = []
    with open(fastq_list_csv, mode="r", encoding="utf8") as file:
        for row in csv.DictReader(file):
            entry: DragenFastqListEntry = DragenFastqListEntry.model_validate(row)
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
def document_reference_for_drs_object(
    drs_object: DrsObject,
    specimen: Specimen,
    ods_code: str,
    pair_num: int | None = None,
) -> DocumentReference:
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
            coding=[Coding(system="http://genomics-file-types.com", code="FASTQ")]
        ),
        content=[
            DocumentReferenceContent(
                attachment=Attachment(
                    url=drs_object.self_uri,
                    contentType=drs_object.mime_type,
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
                        system="http://genomics-file-types.com",
                        code=f"READ-GROUP-{pair_num}",
                    )
                ]
            )
        ]

    return document_reference


@typing.no_type_check
def fastq_list_entry_to_document_references(
    entry: DragenFastqListEntry,
    specimen: Specimen,
    ods_code: str,
    api_base_url: str,
    headers: dict[str, str],
    dry_run: bool = False,
) -> list[DocumentReference]:
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

        read2_doc_ref: DocumentReference = document_reference_for_drs_object(
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
def map_entries_to_fhir(
    entries: list[DragenFastqListEntry],
    ngis_participant_id: str,
    ngis_referral_id: str,
    ods_code: str,
    api_base_url: str,
    headers: dict[str, str] | None = None,
    dry_run: bool = False,
) -> Bundle:
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
                system=f"https://{ods_code}.com/lab-sample-id", value=entries[0].RGSM
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

    return Bundle(
        type=BundleType.TRANSACTION,
        entry=[
            BundleEntry(
                fullUrl=f"urn:uuid:{resource.id}",
                resource=resource,
                request=BundleEntryRequest(
                    method=BundleRequestMethod.POST, url=resource.resource_type
                ),
            )
            for resource in [specimen] + document_references
        ],
    )


def upload_sample_from_fastq_list(
    fastq_list_csv: Path,
    ngis_participant_id: str,
    ngis_referral_id: str,
    ods_code: str,
    api_base_url: str,
    headers: dict[str, str] | None = None,
    fastq_list_sample_id: str | None = None,
    dry_run: bool = False,
) -> None:
    entries: list[DragenFastqListEntry] = read_dragen_fastq_list(
        fastq_list_csv=fastq_list_csv, fastq_list_sample_id=fastq_list_sample_id
    )

    fhir_resource_bundle: Bundle = map_entries_to_fhir(
        entries=entries,
        ngis_participant_id=ngis_participant_id,
        ngis_referral_id=ngis_referral_id,
        ods_code=ods_code,
        api_base_url=api_base_url,
        headers=headers,
        dry_run=dry_run,
    )

    post_fhir_resource(
        resource=fhir_resource_bundle,  # type: ignore
        api_base_url=api_base_url,
        headers=headers,
        dry_run=dry_run,
    )
