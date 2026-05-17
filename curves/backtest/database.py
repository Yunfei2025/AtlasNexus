# -*- coding: utf-8 -*-
"""
Created on Tue Feb 14 17:22:55 2023

@author: 马云飞
"""

import os 
import pandas as pd
import pickle
from settings.paths import DIR_INPUT, DIR_DATA
from curves.utils.retrieve import retrieveWindBondTS, retrieveWindCNBDCurveTS, retrieveWindBacktestPool
from curves.utils.file import updatePKL

def loadBondDataPKL(btype,prange,update=False):
    try:
        bond_info = pd.read_pickle(os.path.join(DIR_DATA,btype+r'-bondpool.pkl'))
    except Exception as e:
        print(f"Warning: Error loading {btype}-bondpool.pkl with pd.read_pickle: {e}")
        print("Falling back to pickle.load...")
        with open(os.path.join(DIR_DATA,btype+r'-bondpool.pkl'), 'rb') as file:
            bond_info = pickle.load(file)
    if update:
        if btype in ['TBond','CBond']:
            database_bond = retrieveWindBondTS(list(bond_info.index),prange)
        else:
            database_bond = retrieveWindBondTS(list(bond_info.index),prange,close=True)

        database_bond = updatePKL(database_bond,os.path.join(DIR_DATA,btype+'-px.pkl'))
    else:
        try:
            database_bond = pd.read_pickle(os.path.join(DIR_DATA,btype+'-px.pkl'))
        except Exception as e:
            print(f"Warning: Error loading {btype}-px.pkl with pd.read_pickle: {e}")
            print("Falling back to pickle.load...")
            with open(os.path.join(DIR_DATA,btype+'-px.pkl'), 'rb') as file:
                database_bond = pickle.load(file)    
    return database_bond

def loadCNBDCurvePKL(update=False):
    database_cbcv = pd.read_pickle(os.path.join(DIR_DATA,'CNDBCurve-px.pkl'))
    if update:
        for ctype in ['CDB','CGB']:
            database_cbcv[ctype] = retrieveWindCNBDCurveTS(ctype)
        database_cbcv = updatePKL(database_cbcv,os.path.join(DIR_DATA,'CNDBCurve-px.pkl'))
    return database_cbcv

def loadIRSPKL():
    # this file has been updated daily
    cvdata = pd.read_pickle(os.path.join(DIR_INPUT,'database-px.pkl'))
    return cvdata


def loadDB(btype, prange, update):
    if update['pool']:
        dps = prange[0].strftime("%Y%m%d")
        ds  = prange[-1].strftime("%Y%m%d")
        cache_path = os.path.join(DIR_DATA, f'{btype}-bondpool_{dps}-{ds}.pkl')
        canonical_path = os.path.join(DIR_DATA, btype + '-bondpool.pkl')

        if os.path.exists(cache_path):
            print(f"Bondpool cache hit — loading {os.path.basename(cache_path)}, skipping WindPy.")
            try:
                bond_info = pd.read_pickle(cache_path)
            except Exception:
                with open(cache_path, 'rb') as f:
                    bond_info = pickle.load(f)
            with open(canonical_path, 'wb') as f:
                pickle.dump(bond_info, f, protocol=pickle.HIGHEST_PROTOCOL)
        else:
            retrieveWindBacktestPool(btype, prange)
            # Cache the result so subsequent runs skip WindPy
            try:
                bond_info = pd.read_pickle(canonical_path)
                with open(cache_path, 'wb') as f:
                    pickle.dump(bond_info, f, protocol=pickle.HIGHEST_PROTOCOL)
                print(f"Bondpool cached to {os.path.basename(cache_path)} for future runs.")
            except Exception as e:
                print(f"Warning: could not write bondpool cache: {e}")

    database = loadBondDataPKL(btype, prange, update['bonds'])
    database.update(loadCNBDCurvePKL(update['cbts']))
    database.update(loadIRSPKL())
    return database
