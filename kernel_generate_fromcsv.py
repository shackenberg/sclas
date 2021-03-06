#!/usr/bin/env python
# -*- coding: utf-8 -*-

# TODO: serious refactoring!

# TODO: clean + pylint
# TODO: chi2-mpi fast
# TODO: multiproc
# TODO: kernel_testtest ?
# TODO: cProfile / line_profiler / kernprof.py / cython?
# DEPENDENCY on numexpr!

# ------------------------------------------------------------------------------

import sys
import os
from os import path
import shutil
import optparse
import csv
import cPickle as pkl

import warnings
warnings.simplefilter('ignore', FutureWarning)

try:
    import scipy as sp
    from scipy import (
        io, linalg,
        )
except ImportError:
    print "scipy is missing (sudo easy_install -U scipy)"
    raise

# TODO: only use numexpr when available (no dependency)
try:
    import numexpr as ne
except ImportError:
    print("**Warning**: numexpr (ne) is missing. "
          "Code may raise exceptions!\n\n")
    #raise

from npprogressbar import *

class OverwriteError(Exception): pass

# ------------------------------------------------------------------------------


DEFAULT_SIMFUNC = "abs_diff"
DEFAULT_KERNEL_TYPE = "dot"
DEFAULT_NOWHITEN = False
DEFAULT_VARIABLE_NAME = "data"
DEFAULT_INPUT_PATH = "./"
DEFAULT_OVERWRITE = False
DEFAULT_NOVERIFY = False
DEFAULT_VERBOSE = False

N_EXIST_CHECK = 10

LIMIT = None

verbose = DEFAULT_VERBOSE

DOT_MAX_NDIMS = 10000
MEAN_MAX_NPOINTS = 2000
STD_MAX_NPOINTS = 2000

VALID_SIMFUNCS = [
    'diff',
    # -- CVPR09
    'abs_diff',
    'sq_diff',    
    'sqrtabs_diff',
    # -- NP Jan 2010
    'mul',
    'sqrt_mul',
    'sq_add',
    'pseudo_AND_soft_range01',
    'concat',
    # -- Others
    #'sq_diff_o_sum',
    # -- DDC Feb 2010
    'normalized_AND_soft', 
    #'normalized_AND_hard_0.5', # poor performance
    #'pseudo_AND_soft', # poor performance
    'pseudo_AND_hard_0.5',
    'pseudo_AND_hard_0.25',
    # -- tmp    
    'tmp',
    'tmp2',
    'tmp4',
    'tmp5',
    'tmp6',
    'tmp7',
    'tmp8',
    'tmp10',
    ]

VALID_KERNEL_TYPES = ["dot", 
                      "ndot",
                      "exp_mu_chi2", 
                      "exp_mu_da",
                      ]

widgets = [RotatingMarker(), " Progress: ", Percentage(), " ",
           Bar(left='[',right=']'), ' ', ETA()]

# ------------------------------------------------------------------------------
def preprocess_features(features,
                        kernel_type = DEFAULT_KERNEL_TYPE,
                        whiten_vectors = None):
    
    assert(kernel_type in VALID_KERNEL_TYPES)

    features.shape = features.shape[0], -1

    if whiten_vectors is not None:
        fmean, fstd = whiten_vectors
        features -= fmean        
        assert((fstd!=0).all())
        features /= fstd

    if kernel_type == "exp_mu_chi2":
        fdiv = features.sum(1)[:,None]
        fdiv[fdiv==0] = 1
        return features / fdiv
    
    return features
    
# ------------------------------------------------------------------------------
def chi2_fromfeatures(features1,
                      features2 = None):

    if features2 is None:
        features2 = features1

    # set up progress bar        
    nfeat1 = len(features1)
    nfeat2 = len(features2)
    niter = nfeat1 * nfeat2
    pbar = ProgressBar(widgets=widgets, maxval=niter)
    pbar.start()

    # go
    n = 0
    kernelmatrix = sp.empty((nfeat1, nfeat2), dtype="float32")

    if features1 is features2:
        for ifeat1, feat1 in enumerate(features1):
            for ifeat2, feat2 in enumerate(features2):
                if ifeat1 == ifeat2:
                    kernelmatrix[ifeat1, ifeat2] = 0
                elif ifeat1 > ifeat2:
                    chi2dist = ne.evaluate("(((feat1 - feat2) ** 2.) / (feat1 + feat2) )")
                    chi2dist[sp.isnan(chi2dist)] = 0
                    chi2dist = chi2dist.sum()
                    kernelmatrix[ifeat1, ifeat2] = chi2dist
                    kernelmatrix[ifeat2, ifeat1] = chi2dist
                pbar.update(n+1)
                n += 1
    else:
        for ifeat1, feat1 in enumerate(features1):
            for ifeat2, feat2 in enumerate(features2):
                chi2dist = ne.evaluate("(((feat1 - feat2) ** 2.) / (feat1 + feat2) )")
                chi2dist[sp.isnan(chi2dist)] = 0
                chi2dist = chi2dist.sum()
                kernelmatrix[ifeat1, ifeat2] = chi2dist
                pbar.update(n+1)
                n += 1

    pbar.finish()    
    print "-"*80

    return kernelmatrix

# ------------------------------------------------------------------------------
def da_fromfeatures(features1,
                    features2 = None):

    if features2 is None:
        features2 = features1
        
    nfeat1 = len(features1)
    nfeat2 = len(features2)

    # go
    kernelmatrix = sp.empty((nfeat1, nfeat2), dtype="float32")

    if features1 is features2:

        # set up progress bar        
        n = 0
        niter = (nfeat1 * (nfeat2+1)) / 2
        pbar = ProgressBar(widgets=widgets, maxval=niter)
        pbar.start()

        for ifeat1, feat1 in enumerate(features1):

            # XXX: this is a hack that will only work with geometric blur d=204
            feat1 = feat1.reshape(-1, 204).copy()                    
            a2 = (feat1**2.).sum(1)[:,None]
        
            for ifeat2, feat2 in enumerate(features2):
                
                if ifeat1 == ifeat2:
                    kernelmatrix[ifeat1, ifeat2] = 0

                elif ifeat1 > ifeat2:
                    # XXX: this is a hack that will only work with geometric blur d=204
                    feat2 = feat2.reshape(-1, 204).copy()


                    ab = sp.dot(feat1, feat2.T)
                    
                    b2 = (feat2**2.).sum(1)[None,:]
                    res = (a2 - 2 *ab + b2)
            
                    dist = res.min(0).mean() + res.min(1).mean()

                    kernelmatrix[ifeat1, ifeat2] = dist
                    kernelmatrix[ifeat2, ifeat1] = dist
                    
                    pbar.update(n+1)
                    n += 1
    else:

        # set up progress bar        
        n = 0
        niter = nfeat1 * nfeat2
        pbar = ProgressBar(widgets=widgets, maxval=niter)
        pbar.start()

        for ifeat1, feat1 in enumerate(features1):

            # XXX: this is a hack that will only work with geometric blur d=204
            feat1 = feat1.reshape(-1, 204).copy()                    
            a2 = (feat1**2.).sum(1)[:,None]
        
            for ifeat2, feat2 in enumerate(features2):
                
                # XXX: this is a hack that will only work with geometric blur d=204
                feat2 = feat2.reshape(-1, 204).copy()


                ab = sp.dot(feat1, feat2.T)
                    
                b2 = (feat2**2.).sum(1)[None,:]
                res = (a2 - 2 *ab + b2)
                    
                dist = res.min(0).mean() + res.min(1).mean()
                
                kernelmatrix[ifeat1, ifeat2] = dist
                    
                pbar.update(n+1)
                n += 1        

    pbar.finish()
    print "-"*80

    return kernelmatrix

# ------------------------------------------------------------------------------
def dot_fromfeatures(features1,
                     features2 = None):

    if features2 is None:
        features2 = features1

    npoints1 = features1.shape[0]
    npoints2 = features2.shape[0]

    features1.shape = npoints1, -1
    features2.shape = npoints2, -1

    ndims = features1.shape[1]
    assert(features2.shape[1] == ndims)

    if ndims < DOT_MAX_NDIMS:
        out = sp.dot(features1, features2.T)
    else:
        out = sp.dot(features1[:,:DOT_MAX_NDIMS], 
                     features2[:,:DOT_MAX_NDIMS].T)
        ndims_done = DOT_MAX_NDIMS            
        while ndims_done < ndims:
            out += sp.dot(features1[:,ndims_done:ndims_done+DOT_MAX_NDIMS], 
                          features2[:,ndims_done:ndims_done+DOT_MAX_NDIMS].T)
            ndims_done += DOT_MAX_NDIMS
            
    return out

# ------------------------------------------------------------------------------
def ndot_fromfeatures(features1,
                     features2 = None):

    features1.shape = features1.shape[0], -1
    features1 = features1/sp.sqrt((features1**2.).sum(1))[:,None]

    if features2 is None:
        features2 = features1
    else:
        features2.shape = features2.shape[0], -1
        features2 = features2/sp.sqrt((features2**2.).sum(1))[:,None]

    return sp.dot(features1, features2.T)

# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# def get_fvector2(fnames,
#                 kernel_type,
#                 variable_name,
#                 simfunc = DEFAULT_SIMFUNC):

#     assert simfunc in VALID_SIMFUNCS

#     if len(fnames) == 1:
#         fvector = load_fname(fnames[0], kernel_type, variable_name)
#     elif len(fnames) == 2:
#         fname1, fname2 = fnames
#         fdata1 = load_fname(fname1, kernel_type, variable_name)
#         fdata2 = load_fname(fname2, kernel_type, variable_name)
#         assert fdata1.shape == fdata2.shape, "with %s and %s" % (fname1, fname2)

#         if simfunc == 'abs_diff':
#             fvector = sp.absolute(fdata1-fdata2)

#         elif simfunc == 'sq_diff':
#             fvector = (fdata1-fdata2)**2.

# #         elif simfunc == 'sq_diff_o_sum':
# #             denom = (fdata1+fdata2)
# #             denom[denom==0] = 1
# #             fvector = ((fdata1-fdata2)**2.) / denom

#         elif simfunc == 'sqrtabs_diff':
#             fvector = sp.sqrt(sp.absolute(fdata1-fdata2))

#         elif simfunc == 'mul':
#             fvector = fdata1*fdata2

#         elif simfunc == 'sqrt_mul':
#             fvector = sp.sqrt(fdata1*fdata2)

#         elif simfunc == 'sq_add':
#             fvector = (fdata1 + fdata2)**2.

#         elif simfunc == 'pseudo_AND_soft_range01':
#             assert fdata1.min() != fdata1.max()
#             fdata1 -= fdata1.min()
#             fdata1 /= fdata1.max()
#             assert fdata2.min() != fdata2.max()
#             fdata2 -= fdata2.min()
#             fdata2 /= fdata2.max()
#             denom = fdata1 + fdata2
#             fvector = 4. * (fdata1 / denom) * (fdata2 / denom)
#             sp.putmask(fvector, sp.isnan(fvector), 0)
#             sp.putmask(fvector, sp.isinf(fvector), 0)                        

#         # DDC additions, FWTW:
#         elif simfunc == 'normalized_AND_soft':
#             fvector = (fdata1 / fdata1.std()) * (fdata2 / fdata2.std())

#         elif simfunc == 'normalized_AND_hard_0.5':
#             fvector = ((fdata1 / fdata1.std()) * (fdata2 / fdata2.std()) > 0.5)

#         elif simfunc == 'pseudo_AND_soft':
#             # this is very similar to mul.  I think it may be one "explanation" for why mul is good
#             denom = fdata1 + fdata2
#             # goes from 1 when fdata1==fdata2, to 0 when they are very different
#             fvector = 4. * (fdata1 / denom) * (fdata2 / denom)  
#             fvector[sp.isnan(fvector)] = 1 # correct behavior is to have the *result* be one
#             fvector[sp.isinf(fvector)] = 1

#         elif simfunc == 'pseudo_AND_hard_0.5':
#             denom = fdata1 + fdata2
#             # goes from 1 when fdata1==fdata2, to 0 when they are very different
#             fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.5 )        

#         elif simfunc == 'pseudo_AND_hard_0.25':
#             denom = fdata1 + fdata2
#             # goes from 1 when fdata1==fdata2, to 0 when they are very different
#             fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.25 )
            
#         elif simfunc == 'tmp':
#             fvector = fdata1**2. + fdata2**2.

#         elif simfunc == 'tmp2':
#             fvector = fdata1**2. + fdata1*fdata2 + fdata2**2.

#         #elif simfunc == 'pseudo_AND_soft':
#         elif simfunc == 'tmp4':
#             # this is very similar to mul.  I think it may be one "explanation" for why mul is good
#             denom = fdata1 + fdata2
#             denom[denom==0] = 1
#             # goes from 1 when fdata1==fdata2, to 0 when they are very different
#             fvector = 4. * (fdata1 / denom) * (fdata2 / denom)          

#         #elif simfunc == 'pseudo_AND_hard_0.5':
#         elif simfunc == 'tmp5':        
#             denom = fdata1 + fdata2
#             denom[denom==0] = 1
#             # goes from 1 when fdata1==fdata2, to 0 when they are very different
#             fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.5 )
        
#         #elif simfunc == 'pseudo_AND_hard_0.25':
#         elif simfunc == 'tmp6':                
#             denom = fdata1 + fdata2
#             denom[denom==0] = 1
#             # goes from 1 when fdata1==fdata2, to 0 when they are very different
#             fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.25 )
            
#         elif simfunc == 'tmp7':                
#             denom = fdata1 + fdata2
#             denom[denom==0] = 1
#             # goes from 1 when fdata1==fdata2, to 0 when they are very different
#             fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.1 )            
#         elif simfunc == 'tmp8':
#             #assert fdata1.min() != fdata1.max()
#             #fdata1 -= fdata1.min()
#             #fdata1 /= fdata1.max()
#             #assert fdata2.min() != fdata2.max()
#             #fdata2 -= fdata2.min()
#             #fdata2 /= fdata2.max()
#             denom = fdata1 + fdata2
#             fvector = 4. * (fdata1 / denom) * (fdata2 / denom)
#             #sp.putmask(fvector, sp.isnan(fvector), 0)
#             fvector[sp.isnan(fvector)] = 0
#             fvector[sp.isinf(fvector)] = 0
#             assert(not sp.isnan(fvector).any())
            
#         elif simfunc == 'tmp10':
#             assert fdata1.min() != fdata1.max()
#             fdata1 -= fdata1.min()
#             fdata1 /= fdata1.max()
#             assert fdata2.min() != fdata2.max()
#             fdata2 -= fdata2.min()
#             fdata2 /= fdata2.max()
#             denom = fdata1 + fdata2
#             #fvector = 4. * (fdata1 / denom) * (fdata2 / denom)
#             fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.25 )
#             #sp.putmask(fvector, sp.isnan(fvector), 0)
#             fvector[sp.isnan(fvector)] = 0
#             fvector[sp.isinf(fvector)] = 0
#             assert(not sp.isnan(fvector).any())
#     else:
#         raise ValueError("len(fnames) == %d" % len(fnames))
 
#     return fvector

# ------------------------------------------------------------------------------
def get_simfunc_fvector(fdata1, fdata2, simfunc=DEFAULT_SIMFUNC):

    assert simfunc in VALID_SIMFUNCS

    if simfunc == 'diff':
        fvector = fdata1-fdata2

    elif simfunc == 'abs_diff':
        fvector = sp.absolute(fdata1-fdata2)

    elif simfunc == 'sq_diff':
        fvector = (fdata1-fdata2)**2.

    elif simfunc == 'sq_diff_o_sum':
        denom = (fdata1+fdata2)
        denom[denom==0] = 1
        fvector = ((fdata1-fdata2)**2.) / denom

    elif simfunc == 'sqrtabs_diff':
        fvector = sp.sqrt(sp.absolute(fdata1-fdata2))

    elif simfunc == 'mul':
        fvector = fdata1*fdata2

    elif simfunc == 'sqrt_mul':
        fvector = sp.sqrt(fdata1*fdata2)

    elif simfunc == 'sq_add':
        fvector = (fdata1 + fdata2)**2.

    elif simfunc == 'pseudo_AND_soft_range01':
        assert fdata1.min() != fdata1.max()
        fdata1 -= fdata1.min()
        fdata1 /= fdata1.max()
        assert fdata2.min() != fdata2.max()
        fdata2 -= fdata2.min()
        fdata2 /= fdata2.max()
        denom = fdata1 + fdata2
        fvector = 4. * (fdata1 / denom) * (fdata2 / denom)
        sp.putmask(fvector, sp.isnan(fvector), 0)
        sp.putmask(fvector, sp.isinf(fvector), 0)                        

    elif simfunc == 'concat':
        return sp.concatenate((fdata1, fdata2))

    # DDC additions, FWTW:
    elif simfunc == 'normalized_AND_soft':
        fvector = (fdata1 / fdata1.std()) * (fdata2 / fdata2.std())

    elif simfunc == 'normalized_AND_hard_0.5':
        fvector = ((fdata1 / fdata1.std()) * (fdata2 / fdata2.std()) > 0.5)

    elif simfunc == 'pseudo_AND_soft':
        # this is very similar to mul.  I think it may be one "explanation" for why mul is good
        denom = fdata1 + fdata2
        # goes from 1 when fdata1==fdata2, to 0 when they are very different
        fvector = 4. * (fdata1 / denom) * (fdata2 / denom)  
        fvector[sp.isnan(fvector)] = 1 # correct behavior is to have the *result* be one
        fvector[sp.isinf(fvector)] = 1

    elif simfunc == 'pseudo_AND_hard_0.5':
        denom = fdata1 + fdata2
        # goes from 1 when fdata1==fdata2, to 0 when they are very different
        fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.5 )        

    elif simfunc == 'pseudo_AND_hard_0.25':
        denom = fdata1 + fdata2
        # goes from 1 when fdata1==fdata2, to 0 when they are very different
        fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.25 )

    elif simfunc == 'tmp':
        fvector = fdata1**2. + fdata2**2.

    elif simfunc == 'tmp2':
        fvector = fdata1**2. + fdata1*fdata2 + fdata2**2.

    #elif simfunc == 'pseudo_AND_soft':
    elif simfunc == 'tmp4':
        # this is very similar to mul.  I think it may be one "explanation" for why mul is good
        denom = fdata1 + fdata2
        denom[denom==0] = 1
        # goes from 1 when fdata1==fdata2, to 0 when they are very different
        fvector = 4. * (fdata1 / denom) * (fdata2 / denom)          

    #elif simfunc == 'pseudo_AND_hard_0.5':
    elif simfunc == 'tmp5':        
        denom = fdata1 + fdata2
        denom[denom==0] = 1
        # goes from 1 when fdata1==fdata2, to 0 when they are very different
        fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.5 )

    #elif simfunc == 'pseudo_AND_hard_0.25':
    elif simfunc == 'tmp6':                
        denom = fdata1 + fdata2
        denom[denom==0] = 1
        # goes from 1 when fdata1==fdata2, to 0 when they are very different
        fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.25 )

    elif simfunc == 'tmp7':                
        denom = fdata1 + fdata2
        denom[denom==0] = 1
        # goes from 1 when fdata1==fdata2, to 0 when they are very different
        fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.1 )            
    elif simfunc == 'tmp8':
        #assert fdata1.min() != fdata1.max()
        #fdata1 -= fdata1.min()
        #fdata1 /= fdata1.max()
        #assert fdata2.min() != fdata2.max()
        #fdata2 -= fdata2.min()
        #fdata2 /= fdata2.max()
        denom = fdata1 + fdata2
        fvector = 4. * (fdata1 / denom) * (fdata2 / denom)
        #sp.putmask(fvector, sp.isnan(fvector), 0)
        fvector[sp.isnan(fvector)] = 0
        fvector[sp.isinf(fvector)] = 0
        assert(not sp.isnan(fvector).any())

    elif simfunc == 'tmp10':
        assert fdata1.min() != fdata1.max()
        fdata1 -= fdata1.min()
        fdata1 /= fdata1.max()
        assert fdata2.min() != fdata2.max()
        fdata2 -= fdata2.min()
        fdata2 /= fdata2.max()
        denom = fdata1 + fdata2
        #fvector = 4. * (fdata1 / denom) * (fdata2 / denom)
        fvector = ( (4. * (fdata1 / denom) * (fdata2 / denom)) > 0.25 )
        #sp.putmask(fvector, sp.isnan(fvector), 0)
        fvector[sp.isnan(fvector)] = 0
        fvector[sp.isinf(fvector)] = 0
        assert(not sp.isnan(fvector).any())

    return fvector
        
# ------------------------------------------------------------------------------
class GetFvectorBase(object):

    def initialize(self,
                   ori_train_fnames,
                   ori_test_fnames,
                   noverify=DEFAULT_NOVERIFY):
        input_suffix = self.input_suffix
        input_path = self.input_path
        train_fnames = [ [ path.join(input_path, fname+input_suffix)                       
                           for fname in fnames ]
                         for fnames in ori_train_fnames ][:LIMIT]
        
        test_fnames = [ [ path.join(input_path, fname+input_suffix)
                          for fname in fnames ]
                        for fnames in ori_test_fnames ][:LIMIT]

        ntrain = len(train_fnames)
        ntest = len(test_fnames)

        if not noverify:
            all_fnames = sp.array(train_fnames+test_fnames).ravel()
            for n, fname in enumerate(all_fnames):
                sys.stdout.write("Verifying that all necessary files exist:"
                                 " %02.2f%%\r" % (100.*(n+1)/all_fnames.size))
                sys.stdout.flush()
                if not path.exists(fname):
                    raise IOError("File '%s' doesn't exist!" % fname)
                if path.getsize(fname)==0:
                    raise IOError("File '%s' is empty!" % fname)

        # --
        self.train_fnames = train_fnames
        self.test_fnames = test_fnames

    def _process_image(self, fname):
        raise NotImplementedError("abstract method")
            
    def get_fvector(self,
                    one_or_two_fnames,
                    kernel_type,
                    simfunc = DEFAULT_SIMFUNC):


        input_path = self.input_path
        
        if len(one_or_two_fnames) == 1:
            fname = path.join(input_path, one_or_two_fnames[0])
            if fname not in self._cache:                
                fvector = self._process_image(fname)
                self._cache[fname] = fvector.copy()
            else:
                fvector = self._cache[fname].copy()
        elif len(one_or_two_fnames) == 2:
            fname1 = path.join(input_path, one_or_two_fnames[0])
            fname2 = path.join(input_path, one_or_two_fnames[1])
            if (fname1, fname2) not in self._cache:
                fdata1 = self._process_image(fname1)
                fdata2 = self._process_image(fname2)
                assert fdata1.shape == fdata2.shape, "with %s and %s" % (fname1, fname2)
                fvector = get_simfunc_fvector(
                    fdata1, fdata2, simfunc=simfunc)
                self._cache[(fname1, fname2)] = fvector.copy()
            else:
                fvector = self._cache[(fname1, fname2)].copy()

        else:
            raise ValueError("len(one_or_two_fnames) = %d" % len(one_or_two_fnames))

        return fvector        
        
class GetFvectorFromSuffix(GetFvectorBase):
    
    def __init__(self,
                 input_suffix,
                 kernel_type = DEFAULT_KERNEL_TYPE,
                 input_path = DEFAULT_INPUT_PATH,
                 variable_name = DEFAULT_VARIABLE_NAME):
        
        self.input_path = input_path
        self.input_suffix = input_suffix
        self.kernel_type = kernel_type
        self.variable_name = variable_name
        self._cache = {}

    def _load_image(self, fname):
        variable_name = self.variable_name

        if fname.endswith('.mat'):
            return io.loadmat(fname)[variable_name]
        elif fname.endswith('.pkl'):
            return pkl.load(open(fname))[variable_name]
        else:
            return sp.misc.imread(fname)

    def _process_image(self, fname):

        kernel_type = self.kernel_type
        variable_name = self.variable_name

        fname += self.input_suffix

        error = False
        try:
            if kernel_type == "exp_mu_da":
                # hack for GB with 204 dims
                #fdata = io.loadmat(fname)[variable_name].reshape(-1, 204)
                fdata = self._load_image(fname).reshape(-1, 204)
            else:
                fdata = self._load_image(fname).ravel()
                #fdata = io.loadmat(fname)[variable_name].ravel()

        except TypeError:
            fname_error = fname+'.error'
            print "[ERROR] couldn't open", fname, "moving it to", fname_error
            #os.unlink(fname)
            shutil.move(fname, fname_error)
            error = True

        except:
            print "[ERROR] (unknown) with", fname
            raise

        if error:
            raise RuntimeError("An error occured while loading '%s'"
                               % fname)

        assert(not sp.isnan(fdata).any())
        assert(not sp.isinf(fdata).any())

        return fdata


# ------------------------------------------------------------------------------
def kernel_generate_fromcsv(input_csv_fname,
                            #input_suffix,
                            output_fname,
                            # --
                            get_fvector_obj,
                            # -- 
                            simfunc = DEFAULT_SIMFUNC,
                            kernel_type = DEFAULT_KERNEL_TYPE,
                            nowhiten = DEFAULT_NOWHITEN,
                            # --
                            variable_name = DEFAULT_VARIABLE_NAME,
                            #input_path = DEFAULT_INPUT_PATH,
                            # --
                            overwrite = DEFAULT_OVERWRITE,
                            noverify = DEFAULT_NOVERIFY,
                            ):

    assert(kernel_type in VALID_KERNEL_TYPES)

    # add matlab's extension to the output filename if needed
    if path.splitext(output_fname)[-1] != ".mat":
        output_fname += ".mat"        

    # can we overwrite ?
    if path.exists(output_fname) and not overwrite:
        warnings.warn("not allowed to overwrite %s"  % output_fname)
        return
        
    # --------------------------------------------------------------------------
    # -- get training and testing filenames from csv 
    print "Processing %s ..." % input_csv_fname
    csvr = csv.reader(open(input_csv_fname))
    rows = [ row for row in csvr ]
    ori_train_fnames = [ row[:-2] for row in rows if row[-1] == "train" ][:LIMIT]
    train_labels = [ row[-2] for row in rows if row[-1] == "train" ][:LIMIT]
    
    ori_test_fnames = [ row[:-2] for row in rows if row[-1] == "test" ][:LIMIT]
    test_labels = [ row[-2] for row in rows if row[-1] == "test" ][:LIMIT]

    ntrain = len(ori_train_fnames)
    ntest = len(ori_test_fnames)

    assert(ntrain>0)
    assert(ntest>0)

    get_fvector_obj.initialize(ori_train_fnames, ori_test_fnames, noverify=noverify)
    get_fvector_func = get_fvector_obj.get_fvector

    # --------------------------------------------------------------------------
    # -- init
    # load first vector to get dimensionality
    fvector0 =  get_fvector_func(ori_train_fnames[0],
                                 kernel_type,
                                 simfunc=simfunc)
        
    if kernel_type == "exp_mu_da":
        # hack for GB with 204 dims
        fvector0 = fvector0.reshape(-1, 204)
    else:
        fvector0 = fvector0.ravel()
    featshape = fvector0.shape
    featsize = fvector0.size

    # -- helper function
    # set up progress bar
    def load_features(x_fnames, get_fvector_func, info_str = 'the'):        
        print "-"*80
        print "Loading %s data ..." % info_str
        pbar = ProgressBar(widgets=widgets, maxval=len(x_fnames))
        pbar.start()

        x_features = sp.empty((len(x_fnames),) + featshape,
                              dtype='float32')
        
        for i, one_or_two_fnames in enumerate(x_fnames):

            # can we overwrite ?
            if (i % N_EXIST_CHECK == 0) \
                   and path.exists(output_fname) \
                   and not overwrite:
                raise OverwriteError("not allowed to overwrite %s"  % output_fname)
            
            fvector = get_fvector_func(one_or_two_fnames,
                                       kernel_type,
                                       simfunc=simfunc)
            fvector = fvector.reshape(fvector0.shape)
            x_features[i] = fvector
            pbar.update(i+1)

        pbar.finish()
        print "-"*80        

        return x_features

    # -- load features from train filenames
    try:
        train_features = load_features(ori_train_fnames,
                                       get_fvector_func,
                                       info_str = 'training')
    except OverwriteError, err:
        print err
        return 
        
    # -- train x train
    print "Preprocessing train features ..."
    if nowhiten:
        whiten_vectors = None
    else:
        fshape = train_features.shape
        train_features.shape = fshape[0], -1
        npoints, ndims = train_features.shape

        if npoints < MEAN_MAX_NPOINTS:
            fmean = train_features.mean(0)
        else:
            # - try to optimize memory usage...
            sel = train_features[:MEAN_MAX_NPOINTS]
            fmean = sp.empty_like(sel[0,:])

            sp.add.reduce(sel, axis=0, dtype="float32", out=fmean)

            curr = sp.empty_like(fmean)
            npoints_done = MEAN_MAX_NPOINTS
            while npoints_done < npoints:

                # check if can we overwrite (other process)
                if path.exists(output_fname) and not overwrite:
                    warnings.warn("not allowed to overwrite %s"  % output_fname)
                    return
                
                sel = train_features[npoints_done:npoints_done+MEAN_MAX_NPOINTS]
                sp.add.reduce(sel, axis=0, dtype="float32", out=curr)
                sp.add(fmean, curr, fmean)
                npoints_done += MEAN_MAX_NPOINTS                
     
            #fmean = train_features[:MEAN_MAX_NPOINTS].sum(0)
            #npoints_done = MEAN_MAX_NPOINTS
            #while npoints_done < npoints:
            #    fmean += train_features[npoints_done:npoints_done+MEAN_MAX_NPOINTS].sum(0)
            #    npoints_done += MEAN_MAX_NPOINTS

            fmean /= npoints

        if npoints < STD_MAX_NPOINTS:
            fstd = train_features.std(0)
        else:
            # - try to optimize memory usage...

            sel = train_features[:MEAN_MAX_NPOINTS]

            mem = sp.empty_like(sel)
            curr = sp.empty_like(mem[0,:])

            seln = sel.shape[0]
            sp.subtract(sel, fmean, mem[:seln])
            sp.multiply(mem[:seln], mem[:seln], mem[:seln])
            fstd = sp.add.reduce(mem[:seln], axis=0, dtype="float32")

            npoints_done = MEAN_MAX_NPOINTS
            while npoints_done < npoints:

                # check if can we overwrite (other process)
                if path.exists(output_fname) and not overwrite:
                    warnings.warn("not allowed to overwrite %s"  % output_fname)
                    return

                sel = train_features[npoints_done:npoints_done+MEAN_MAX_NPOINTS]
                seln = sel.shape[0]
                sp.subtract(sel, fmean, mem[:seln])
                sp.multiply(mem[:seln], mem[:seln], mem[:seln])
                sp.add.reduce(mem[:seln], axis=0, dtype="float32", out=curr)
                sp.add(fstd, curr, fstd)

                npoints_done += MEAN_MAX_NPOINTS

            # slow version:
            #fstd = ((train_features[:MEAN_MAX_NPOINTS]-fmean)**2.).sum(0)
            #npoints_done = MEAN_MAX_NPOINTS
            #while npoints_done < npoints:
            #    fstd += ((train_features[npoints_done:npoints_done+MEAN_MAX_NPOINTS]-fmean)**2.).sum(0)
            #    npoints_done += MEAN_MAX_NPOINTS

            fstd = sp.sqrt(fstd/npoints)

        fstd[fstd==0] = 1
        whiten_vectors = (fmean, fstd)
        train_features.shape = fshape

    assert(not sp.isnan(sp.ravel(train_features)).any())
    assert(not sp.isinf(sp.ravel(train_features)).any())

    # check if can we overwrite (other process)
    if path.exists(output_fname) and not overwrite:
        warnings.warn("not allowed to overwrite %s"  % output_fname)
        return
                
    train_features = preprocess_features(train_features, 
                                         kernel_type = kernel_type,
                                         whiten_vectors = whiten_vectors)

    assert(not sp.isnan(sp.ravel(train_features)).any())
    assert(not sp.isinf(sp.ravel(train_features)).any())

    # check if can we overwrite (other process)
    if path.exists(output_fname) and not overwrite:
        warnings.warn("not allowed to overwrite %s"  % output_fname)
        return
                
    print "Computing '%s' kernel_traintrain ..." % (kernel_type)
    if kernel_type == "dot":
        kernel_traintrain = dot_fromfeatures(train_features)
    elif kernel_type == "ndot":
        kernel_traintrain = ndot_fromfeatures(train_features)
    elif kernel_type == "exp_mu_chi2":
        chi2_matrix = chi2_fromfeatures(train_features)
        chi2_mu_train = chi2_matrix.mean()
        kernel_traintrain = ne.evaluate("exp(-chi2_matrix/chi2_mu_train)")        
    elif kernel_type == "exp_mu_da":
        da_matrix = da_fromfeatures(train_features)
        da_mu_train = da_matrix.mean()
        kernel_traintrain = ne.evaluate("exp(-da_matrix/da_mu_train)")

    assert(not (kernel_traintrain==0).all())

    # --------------------------------------------------------------------------
    # -- load features from test filenames
    try:
        test_features = load_features(ori_test_fnames,
                                      get_fvector_func,
                                      info_str = 'testing')
    except OverwriteError, err:
        print err
        return   
  
    # -- train x test
    print "Preprocessing test features ..."
    test_features = preprocess_features(test_features, 
                                        kernel_type = kernel_type,
                                        whiten_vectors = whiten_vectors)
    assert(not sp.isnan(test_features).any())
    assert(not sp.isinf(test_features).any())

    # check if can we overwrite (other process)
    if path.exists(output_fname) and not overwrite:
        warnings.warn("not allowed to overwrite %s"  % output_fname)
        return
                
    print "Computing '%s' kernel_traintest ..."  % (kernel_type)
    if kernel_type == "dot":
        kernel_traintest = dot_fromfeatures(train_features, test_features)
    elif kernel_type == "ndot":
        kernel_traintest = ndot_fromfeatures(train_features, test_features)
    elif kernel_type == "exp_mu_chi2":
        chi2_matrix = chi2_fromfeatures(train_features, test_features)
        kernel_traintest = ne.evaluate("exp(-chi2_matrix/chi2_mu_train)")        
    elif kernel_type == "exp_mu_da":
        da_matrix = da_fromfeatures(train_features, test_features)
        kernel_traintest = ne.evaluate("exp(-da_matrix/da_mu_train)")        

    assert(not (kernel_traintest==0).all())
    
    # check if can we overwrite (other process)
    if path.exists(output_fname) and not overwrite:
        warnings.warn("not allowed to overwrite %s"  % output_fname)
        return
                
    # --------------------------------------------------------------------------
    # -- write output file
    print
    print "Writing %s ..." % (output_fname)
    data = {"kernel_traintrain": kernel_traintrain,
            "kernel_traintest": kernel_traintest,
            "train_labels": train_labels,
            "test_labels": test_labels,
            "train_fnames": ori_train_fnames,
            "test_fnames": ori_test_fnames,
            }

    try:
        io.savemat(output_fname, data, format="4")
    except IOError, err:
        print "ERROR!:", err
        

# ------------------------------------------------------------------------------
def get_optparser():
    
    usage = "usage: %prog [options] <input_csv_filename> <input_suffix> <output_filename>"
    
    parser = optparse.OptionParser(usage=usage)
    
    help_str = ("the similarity function to use "
                "(only for 'same/different' protocols) "
                "from the following list: %s. "
                % VALID_SIMFUNCS)
    parser.add_option("--simfunc", "-s",
                      type="choice",                      
                      #metavar="STR",
                      choices=VALID_SIMFUNCS,
                      default=DEFAULT_SIMFUNC,
                      help=help_str+"[DEFAULT='%default']"                      
                      )

    parser.add_option("--kernel_type", "-k",
                      type="str",                      
                      metavar="STR",
                      default=DEFAULT_KERNEL_TYPE,
                      help="'dot', 'exp_mu_chi2', 'exp_mu_da' [DEFAULT='%default']")
    # TODO: 'cosine', 'exp_mu_intersect', 'intersect', 'chi2' ?

    parser.add_option("--nowhiten",
                      default=DEFAULT_NOWHITEN,
                      action="store_true",
                      help="[DEFAULT=%default]")

    parser.add_option("--variable_name", "-n",
                      metavar="STR",
                      type="str",
                      default=DEFAULT_VARIABLE_NAME,
                      help="[DEFAULT='%default']")

    parser.add_option("--input_path", "-i",
                      default=DEFAULT_INPUT_PATH,
                      type="str",
                      metavar="STR",
                      help="[DEFAULT='%default']")
    
    parser.add_option("--overwrite",
                      default=DEFAULT_OVERWRITE,
                      action="store_true",
                      help="overwrite existing file [default=%default]")

    parser.add_option("--noverify",
                      default=DEFAULT_NOVERIFY,
                      action="store_true",
                      help="disable verification of files before loading [default=%default]")

#     parser.add_option("--verbose", "-v" ,
#                       default=DEFAULT_VERBOSE,
#                       action="store_true",
#                       help="[default=%default]")
    # --
    
    
    return parser

    
# ------------------------------------------------------------------------------
def main():

    parser = get_optparser()
    
    opts, args = parser.parse_args()

    if len(args) != 3:
        parser.print_help()
    else:
        input_csv_fname = args[0]
        input_suffix = args[1]
        output_fname = args[2]


        get_vector_class = GetFvectorFromSuffix
        get_vector_obj = get_vector_class(
            input_suffix,
            opts.kernel_type,
            input_path = opts.input_path,
            variable_name = opts.variable_name)

        kernel_generate_fromcsv(input_csv_fname,
                                #input_suffix,
                                output_fname,
                                # --
                                get_vector_obj,
                                # -- 
                                simfunc = opts.simfunc, 
                                kernel_type = opts.kernel_type,
                                nowhiten = opts.nowhiten,
                                # --
                                variable_name = opts.variable_name,
                                #input_path = opts.input_path,
                                # --
                                overwrite = opts.overwrite,
                                noverify = opts.noverify
                                )

# ------------------------------------------------------------------------------
if __name__ == "__main__":
    main()
