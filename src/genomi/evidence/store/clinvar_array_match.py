from __future__ import annotations

from .clinvar_match_provenance import MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE


def clinvar_array_direct_select_sql(
    table_name: str,
    *,
    chrom_expression: str,
    extra_where: str | None = None,
    cross_build: bool = False,
) -> str:
    where = f"""
              and cv.chrom = {chrom_expression}
              and cv.pos = r.pos
              and cv.genome_build = ?
        """
    if extra_where is not None:
        where += f" and {extra_where}"
    if cross_build:
        # In cross-build mode r.chrom / r.pos are the lifted coords (used by
        # the JOIN); the sample's native coords ride along on
        # sample_chrom_original / sample_pos_original.
        sample_chrom_select = "r.sample_chrom_original as sample_chrom"
        sample_pos_select = "r.sample_pos_original as sample_pos"
        lifted_columns_select = ", r.chrom as lifted_chrom, r.pos as lifted_pos"
    else:
        sample_chrom_select = "r.chrom as sample_chrom"
        sample_pos_select = "r.pos as sample_pos"
        lifted_columns_select = ", null as lifted_chrom, null as lifted_pos"
    return f"""
            select
                cast(r.record_rowid as text) || ':' || cv.alt || ':array' as batch_id,
                '{MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE}' as match_basis,
                '{MATCH_BASIS_CONSUMER_ARRAY_ALLELE_INFERENCE}' as match_kind,
                {sample_chrom_select},
                {sample_pos_select},
                r.rsid as sample_rsid,
                r.ref as sample_ref,
                r.alt as sample_alt,
                cv.ref as inferred_clinvar_ref,
                cv.alt as inferred_clinvar_alt,
                r.qual as sample_qual,
                r.filter as sample_filter,
                r.sample_index as sample_index,
                r.sample_name as sample_name,
                r.genotype as genotype,
                r.depth as depth,
                r.genotype_quality as genotype_quality,
                r.ref as source_record_ref,
                r.alt as source_record_alt,
                r.format as source_record_format,
                r.genotype as source_record_genotype,
                r.record_kind as source_record_kind,
                r.observed_alleles as source_record_observed_alleles,
                r.info as source_record_info,
                null as source_format,
                cv.chrom as chrom,
                cv.pos as pos,
                cv.ref as ref,
                cv.alt as alt,
                cv.genome_build as genome_build,
                cv.clinvar_id as clinvar_id,
                cv.allele_id as allele_id,
                cv.clinical_significance as clinical_significance,
                cv.review_status as review_status,
                cv.conditions as conditions,
                cv.gene_info as gene_info,
                cv.hgvs as hgvs,
                cv.source_path as source_path,
                cv.source_version as source_version,
                cv.imported_at as imported_at
                {lifted_columns_select}
            from selected_records r
            cross join {table_name} as cv indexed by clinvar_variant_idx
            where 1 = 1
              and r.record_kind = 'array_call'
              and upper(cv.ref) in ('A', 'C', 'G', 'T')
              and upper(cv.alt) in ('A', 'C', 'G', 'T')
              and r.genotype is not null
              and length(upper(r.genotype)) between 1 and 2
              and upper(r.genotype) not in ('', '.', '--', '00', 'NN')
              and instr(upper(r.genotype), upper(cv.alt)) > 0
              and replace(replace(upper(r.genotype), upper(cv.ref), ''), upper(cv.alt), '') = ''
              {where}
        """
