# -*- coding: utf-8 -*-
"""Supp.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1chyux4owb6Mwt1_IOO-Y-mHwG_xeO3Fv
"""

"""
Plotting routines for visualizing chemical diversity of datasets
"""

import os
import sys
import pandas as pd
import numpy as np
import seaborn as sns
import umap
from scipy.stats.kde import gaussian_kde
from scipy.cluster.hierarchy import linkage
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import logging
import argparse
from rdkit import Chem
from rdkit.Chem import AllChem, Draw

from atomsci.ddm.utils import struct_utils
from atomsci.ddm.pipeline import dist_metrics as dm
from atomsci.ddm.pipeline import  chem_diversity as cd
from atomsci.ddm.pipeline import  parameter_parser as parse
from atomsci.ddm.pipeline import  model_datasets as md
from atomsci.ddm.pipeline import  featurization as feat
from atomsci.ddm.utils import datastore_functions as dsf

#matplotlib.style.use('ggplot')
matplotlib.rc('xtick', labelsize=12)
matplotlib.rc('ytick', labelsize=12)
matplotlib.rc('axes', labelsize=12)

logging.basicConfig(format='%(asctime)-15s %(message)s')

ndist_max = 1000000

def diversity_plots(dset_key, datastore=True, bucket='gsk_ml', title_prefix=None, ecfp_radius=4, umap_file=None, out_dir=None, 
                    id_col='compound_id', smiles_col='rdkit_smiles', is_base_smiles=False, response_col=None, max_for_mcs=300):
  
    """
    Plot visualizations of diversity for an arbitrary table of compounds. At minimum, the file should contain
    columns for a compound ID and a SMILES string.
    """
    # Load table of compound names, IDs and SMILES strings
    if datastore:
        cmpd_df = dsf.retrieve_dataset_by_datasetkey(dset_key, bucket)
    else:
        cmpd_df = pd.read_csv(dset_key, index_col=False)
    cmpd_df = cmpd_df.drop_duplicates(subset=smiles_col)
    file_prefix = os.path.splitext(os.path.basename(dset_key))[0]
    if title_prefix is None:
        title_prefix = file_prefix.replace('_', ' ')
    compound_ids = cmpd_df[id_col].values
    smiles_strs = cmpd_df[smiles_col].values
    ncmpds = len(smiles_strs)
    # Strip salts, canonicalize SMILES strings and create RDKit Mol objects
    if is_base_smiles:
        base_mols = np.array([Chem.MolFromSmiles(s) for s in smiles_strs])
    else:
        print("Canonicalizing %d molecules..." % ncmpds)
        base_mols = np.array([struct_utils.base_mol_from_smiles(smiles) for smiles in smiles_strs])
        for i, mol in enumerate(base_mols):
            if mol is None:
                print('Unable to get base molecule for compound %d = %s' % (i, compound_ids[i]))
        print("Done")

    has_good_smiles = np.array([mol is not None for mol in base_mols])
    base_mols = base_mols[has_good_smiles]

    cmpd_df = cmpd_df[has_good_smiles]
    ncmpds = cmpd_df.shape[0]
    compound_ids = cmpd_df[id_col].values
    responses = None
    if response_col is not None:
        responses = cmpd_df[response_col].values
        uniq_responses = set(responses)
        if uniq_responses == set([0,1]):
            response_type = 'binary'
            colorpal =  {0 : 'forestgreen', 1 : 'red'}
        elif len(uniq_responses) <= 10:
            response_type = 'categorical'
            colorpal = sns.color_palette('husl', n_colors=len(uniq_responses))
        else:
            response_type = 'continuous'
            colorpal = sns.blend_palette(['red', 'green', 'blue'], 12, as_cmap=True)


    print("generating ECFP")
    # Generate ECFP fingerprints
    print("Computing fingerprints...")
    fps = [AllChem.GetMorganFingerprintAsBitVect(mol, ecfp_radius, 1024) for mol in base_mols if mol is not None]
    print("Done")

    if ncmpds <= max_for_mcs:
        # Get MCS distance matrix and draw a heatmap
        print("Computing MCS distance matrix...")
        mcs_dist = dm.mcs(base_mols)
        print("Done")
        cmpd1 = []
        cmpd2 = []
        dist = []
        ind1 = []
        ind2 = []
        for i in range(ncmpds-1):
            for j in range(i+1, ncmpds):
                cmpd1.append(compound_ids[i])
                cmpd2.append(compound_ids[j])
                dist.append(mcs_dist[i,j])
                ind1.append(i)
                ind2.append(j)
        dist_df = pd.DataFrame({'compound_1' : cmpd1, 'compound_2' : cmpd2, 'dist' : dist,
                                'i' : ind1, 'j' : ind2})
        dist_df = dist_df.sort_values(by='dist')
        print(dist_df.head(10))
        if out_dir is not None:
            dist_df.to_csv('%s/%s_mcs_dist_table.csv' % (out_dir, file_prefix), index=False)
            for k in range(10):
                mol_i = base_mols[dist_df.i.values[k]]
                mol_j = base_mols[dist_df.j.values[k]]
                img_file_i = '%s/%d_%s.png' % (out_dir, k, compound_ids[dist_df.i.values[k]])
                img_file_j = '%s/%d_%s.png' % (out_dir, k, compound_ids[dist_df.j.values[k]])
                Draw.MolToFile(mol_i, img_file_i, size=(500,500), fitImage=False)
                Draw.MolToFile(mol_j, img_file_j, size=(500,500), fitImage=False)
    
        mcs_linkage = linkage(mcs_dist, method='complete')
        mcs_df = pd.DataFrame(mcs_dist, columns=compound_ids, index=compound_ids)
        if out_dir is not None:
            pdf_path = '%s/%s_mcs_clustermap.pdf' % (out_dir, file_prefix)
            pdf = PdfPages(pdf_path)
        g = sns.clustermap(mcs_df, row_linkage=mcs_linkage, col_linkage=mcs_linkage, figsize=(12,12), cmap='plasma')
        if out_dir is not None:
            pdf.savefig(g.fig)
            pdf.close()
    
        # Draw a UMAP projection based on MCS distance
        mapper = umap.UMAP(n_neighbors=20, min_dist=0.1, n_components=2, metric='precomputed', random_state=17)
        reps = mapper.fit_transform(mcs_dist)
        rep_df = pd.DataFrame.from_records(reps, columns=['x', 'y'])
        rep_df['compound_id'] = compound_ids
        if out_dir is not None:
            pdf_path = '%s/%s_mcs_umap_proj.pdf' % (out_dir, file_prefix)
            pdf = PdfPages(pdf_path)
        fig, ax = plt.subplots(figsize=(12,12))
        if responses is None:
            sns.scatterplot(x='x', y='y', data=rep_df, ax=ax)
        else:
            rep_df['response'] = responses
            sns.scatterplot(x='x', y='y', hue='response', palette=colorpal,
                            data=rep_df, ax=ax)
        ax.set_title("%s, 2D projection based on MCS distance" % title_prefix)
        if out_dir is not None:
            pdf.savefig(fig)
            pdf.close()
            rep_df.to_csv('%s/%s_mcs_umap_proj.csv' % (out_dir, file_prefix), index=False)

    # Get Tanimoto distance matrix
    print("Computing Tanimoto distance matrix...")
    tani_dist = dm.tanimoto(fps)
    print("Done")
    # Draw a UMAP projection based on Tanimoto distance
    mapper = umap.UMAP(n_neighbors=20, min_dist=0.1, n_components=2, metric='precomputed', random_state=17)
    reps = mapper.fit_transform(tani_dist)
    rep_df = pd.DataFrame.from_records(reps, columns=['x', 'y'])
    rep_df['compound_id'] = compound_ids
    if responses is not None:
        rep_df['response'] = responses
    if umap_file is not None:
        rep_df.to_csv(umap_file, index=False)
        print("Wrote UMAP mapping to %s" % umap_file)
    if out_dir is not None:
        pdf_path = '%s/%s_tani_umap_proj.pdf' % (out_dir, file_prefix)
        pdf = PdfPages(pdf_path)
    fig, ax = plt.subplots(figsize=(12,12))
    if responses is None:
        sns.scatterplot(x='x', y='y', data=rep_df, ax=ax)
    else:
        sns.scatterplot(x='x', y='y', hue='response', palette=colorpal,
                        data=rep_df, ax=ax)
    ax.set_title("%s, 2D projection based on Tanimoto distance" % title_prefix)
    if out_dir is not None:
        pdf.savefig(fig)
        pdf.close()

    # Draw a cluster heatmap based on Tanimoto distance
    tani_linkage = linkage(tani_dist, method='complete')
    tani_df = pd.DataFrame(tani_dist, columns=compound_ids, index=compound_ids)
    if out_dir is not None:
        pdf_path = '%s/%s_tanimoto_clustermap.pdf' % (out_dir, file_prefix)
        pdf = PdfPages(pdf_path)
    g = sns.clustermap(tani_df, row_linkage=tani_linkage, col_linkage=tani_linkage, figsize=(12,12), cmap='plasma')
    if out_dir is not None:
        pdf.savefig(g.fig)
        pdf.close()


def calc_dist_smiles(
    feat_type, dist_met, smiles_arr1, smiles_arr2=None, calc_type='nearest', num_nearest=1, **metric_kwargs):
    """Returns a vector of distances, either between all compounds in a single matrix or between two matrices.
    
    Args:
        feature_type: How the data should be featurized. Current options include ECFP, MOE, or Dragon7.
        
        dist_met: What distance metric to use. Current options include tanimoto, cosine, cityblock, euclidean, or any
        other metric supported by scipy.spatial.distance.pdist()..
        
        smiles_arr1 (list): List of SMILES strings.
        
        smiles_arr2 (list): Optional, second list of SMILES strings. Can have only 1 member if wanting compound to
        matrix comparison.
        
        calc_type: Type of calculation to use to process distance matrix. Options: nearest, farthest, average, or all.
        
        num_nearest: Additional parameter for calc_types nearest, nth_nearest and avg_n_nearest.

    Returns:
        dists: vector or array of distances
    """
    within_dset = False
    if feat_type in ['ECFP','ecfp'] and dist_met=='tanimoto':
        # TODO: Handle other metrics for fingerprints, as in calc_dist_diskdataset()
        mols1 = [Chem.MolFromSmiles(s) for s in smiles_arr1]
        fprints1 = [AllChem.GetMorganFingerprintAsBitVect(mol, 2, 1024) for mol in mols1]
        if smiles_arr2 is not None:
            if len(smiles_arr2) == 1:
                cpd_mol = Chem.MolFromSmiles(smiles_arr2[0])
                cpd_fprint = AllChem.GetMorganFingerprintAsBitVect(cpd_mol, 2, 1024)
                # Vector of distances
                return calc_summary(dist_metrics.tanimoto_single(cpd_fprint, fprints1)[0], calc_type, 
                                    num_nearest, within_dset)
            else:
                mols2 = [Chem.MolFromSmiles(s) for s in smiles_arr2]
                fprints2 = [AllChem.GetMorganFingerprintAsBitVect(mol, 2, 1024) for mol in mols2]
        else:
            fprints2 = None
            within_dset = True
        return calc_summary(dist_metrics.tanimoto(fprints1, fprints2), calc_type, num_nearest, within_dset)
        
    elif dist_met == 'mcs':
        mols1 = [Chem.MolFromSmiles(s) for s in smiles_arr1]
        n_atms = [mol.GetNumAtoms() for mol in mols1]
        if smiles_arr2 is not None:
            if len(smiles_arr2) == 1:
                cpd_mol = Chem.MolFromSmiles(smiles_arr2[0])
                # Vector of distances
                return calc_summary(dist_metrics.mcs_single(
                    cpd_mol, mols1, n_atms)[0], calc_type, num_nearest, within_dset)
            else:
                mols2 = [Chem.MolFromSmiles(s) for s in smiles_arr2]
        else:
            mols2 = None
        return calc_summary(dist_metrics.mcs(mols1, mols2), calc_type, num_nearest, within_dset=True)
    
    elif feat_type in ['descriptors', 'moe']:
        feats1 = get_descriptors(smiles_arr1)
        if feats1 is not None:
            if smiles_arr2 is not None:
                feats2 = get_descriptors(smiles_arr2)
                if feats2 is None:
                    return
                return calc_summary(cdist(feats1, feats2, dist_met), calc_type, num_nearest, within_dset)
            else:
                return calc_summary(pdist(feats1, dist_met, **metric_kwargs), calc_type, num_nearest, within_dset=True)