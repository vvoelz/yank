#!/usr/bin/env python

"""
A module implementing the multistate Bennett acceptance ratio (MBAR) method for the analysis
of equilibrium samples from multiple arbitrary thermodynamic states in computing equilibrium
expectations, free energy differences, potentials of mean force, and entropy and enthalpy contributions.

Please reference the following if you use this code in your research:

[1] Shirts MR and Chodera JD. Statistically optimal analysis of samples from multiple equilibrium states.
J. Chem. Phys. 129:124105, 2008.  http://dx.doi.org/10.1063/1.2978177

This module contains implementations of

* EXP - unidirectional estimator for free energy differences based on Zwanzig relation / exponential averaging
* BAR - bidirectional estimator for free energy differences / Bennett acceptance ratio estimator
* MBAR - multistate Bennett acceptance ratio estimator

"""

#=============================================================================================
# COPYRIGHT NOTICE
#
# Written by John D. Chodera <jchodera@gmail.com> and Michael R. Shirts <mrshirts@gmail.com>.
#
# Copyright (c) 2006-2007 The Regents of the University of California.  All Rights Reserved.
# Portions of this software are Copyright (c) 2007-2008 Stanford University and Columbia University.
#
# This program is free software; you can redistribute it and/or modify it under the terms of
# the GNU General Public License as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License along with this program;
# if not, write to the Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor,
# Boston, MA  02110-1301, USA.
#=============================================================================================

#=============================================================================================
# TODO
# * Implement fallback to iterative procedure in Newton-Raphson.
# * Make asymptotic covariance matrix computation more robust to over/underflow.
# * Double-check correspondence of comments to equation numbers once manuscript has been finalized.
# * Set up distutils-style installation for _MBAR.cpp compiled code.
# * Change self.nonzero_N_k_indices to self.states_with_samples
#=============================================================================================

#=============================================================================================
# VERSION CONTROL INFORMATION
#=============================================================================================

__version__ = "$Revision: 87 $ $Date: 2009-11-03 21:43:35 -0600 (Tue, 03 Nov 2009) $"
# $Date: 2009-11-03 21:43:35 -0600 (Tue, 03 Nov 2009) $
# $Revision: 87 $
# $LastChangedBy: mrshirts $
# $HeadURL: https://simtk.org/svn/pymbar/trunk/pymbar/pymbar.py $
# $Id: MBAR.py 87 2009-11-04 03:43:35Z mrshirts $

#=============================================================================================
# IMPORTS
#=============================================================================================

import math
import numpy
import numpy.linalg

#=============================================================================================
# Exception class.
#=============================================================================================

class ParameterError(Exception):
  """
  An error in the input parameters has been detected.

  """
  pass

class ConvergenceError(Exception):
  """
  Convergence could not be achieved.

  """
  pass

class BoundsError(Exception):
  """
  Could not determine bounds on free energy

  """
  pass

#=============================================================================================
# Private utility functions
#=============================================================================================

def logsum(a_n):
  """
  Compute the log of a sum of exponentiated terms exp(a_n) in a numerically-stable manner:

    logsum a_n = max_arg + \log \sum_{n=1}^N \exp[a_n - max_arg]

  where max_arg = max_n a_n.  This is mathematically (but not numerically) equivalent to

    logsum a_n = \log \sum_{n=1}^N \exp[a_n]

  ARGUMENTS
    a_n (numpy array) - a_n[n] is the nth exponential argument
  
  RETURNS
    log_sum (float) - the log of the sum of exponentiated a_n, log (\sum_n exp(a_n))

  EXAMPLE  

  >>> a_n = numpy.array([0.0, 1.0, 1.2], numpy.float64)
  >>> print '%.3e' % logsum(a_n)
  1.951e+00
    
  """

  # Compute the maximum argument.
  max_log_term = numpy.max(a_n)

  # Compute the reduced terms.
  terms = numpy.exp(a_n - max_log_term)

  # Compute the log sum.
  log_sum = numpy.log(sum(terms)) + max_log_term
        
  return log_sum

#=============================================================================================
# One-sided exponential averaging (EXP).
#=============================================================================================

def EXP(w_F, compute_uncertainty=True, is_timeseries=False):
  """
  Estimate free energy difference using one-sided (unidirectional) exponential averaging (EXP).

  ARGUMENTS
    w_F (numpy array) - w_F[t] is the forward work value from snapshot t.  t = 0...(T-1)  Length T is deduced from vector.

  OPTIONAL ARGUMENTS
    compute_uncertainty (boolean) - if False, will disable computation of the statistical uncertainty (default: True)
    is_timeseries (boolean) - if True, correlation in data is corrected for by estimation of statisitcal inefficiency (default: False)
                              Use this option if you are providing correlated timeseries data and have not subsampled the data to produce uncorrelated samples.

  RETURNS
    DeltaF (float) - DeltaF is the free energy difference between the two states.
    dDeltaF (float) - dDeltaF is the uncertainty, and is only returned if compute_uncertainty is set to True

  NOTE

    If you are prodividing correlated timeseries data, be sure to set the 'timeseries' flag to True

  EXAMPLES

  Compute the free energy difference given a sample of forward work values.

  >>> import testsystems
  >>> [w_F, w_R] = testsystems.GaussianWorkSample(mu_F=None, DeltaF=1.0, seed=0)
  >>> [DeltaF, dDeltaF] = EXP(w_F)
  >>> print 'Forward free energy difference is %.3f +- %.3f kT' % (DeltaF, dDeltaF)
  Forward free energy difference is 1.088 +- 0.076 kT
  >>> [DeltaF, dDeltaF] = EXP(w_R)
  >>> print 'Reverse free energy difference is %.3f +- %.3f kT' % (DeltaF, dDeltaF)
  Reverse free energy difference is -1.073 +- 0.082 kT
  
  """

  # Get number of work measurements.
  T = float(numpy.size(w_F)) # number of work measurements
  
  # Estimate free energy difference by exponential averaging using DeltaF = - log < exp(-w_F) >
  DeltaF = - ( logsum( - w_F ) - numpy.log(T) )

  if compute_uncertainty:  
    # Compute x_i = numpy.exp(-w_F_i - max_arg)
    max_arg = numpy.max(-w_F) # maximum argument
    x = numpy.exp(-w_F - max_arg)

    # Compute E[x] = <x> and dx
    Ex = x.mean()

    # Compute effective number of uncorrelated samples.
    g = 1.0 # statistical inefficiency
    if is_timeseries:
      # Estimate statistical inefficiency of x timeseries.
      import timeseries
      g = timeseries.statisticalInefficiency(x, x)

    # Estimate standard error of E[x].
    dx = numpy.std(x) / numpy.sqrt(T/g)
        
    # dDeltaF = <x>^-1 dx
    dDeltaF = (dx/Ex)

    # Return estimate of free energy difference and uncertainty.
    return (DeltaF, dDeltaF)
  else:
    return DeltaF


#=============================================================================================
# Gaussian approximation to exponential averaging (Gauss).
#=============================================================================================

def Gauss(w_F, compute_uncertainty=True, is_timeseries=False):
  """
  Estimate free energy difference using one-sided (unidirectional) exponential averaging (EXP).

  ARGUMENTS
    w_F (numpy array) - w_F[t] is the forward work value from snapshot t.  t = 0...(T-1)  Length T is deduced from vector.

  OPTIONAL ARGUMENTS
    compute_uncertainty (boolean) - if False, will disable computation of the statistical uncertainty (default: True)
    is_timeseries (boolean) - if True, correlation in data is corrected for by estimation of statisitcal inefficiency (default: False)
                              Use this option if you are providing correlated timeseries data and have not subsampled the data to produce uncorrelated samples.

  RETURNS
    DeltaF (float) - DeltaF is the free energy difference between the two states.
    dDeltaF (float) - dDeltaF is the uncertainty, and is only returned if compute_uncertainty is set to True

  NOTE

    If you are prodividing correlated timeseries data, be sure to set the 'timeseries' flag to True

  EXAMPLES

  Compute the free energy difference given a sample of forward work values.

  >>> import testsystems
  >>> [w_F, w_R] = testsystems.GaussianWorkSample(mu_F=None, DeltaF=1.0, seed=0)
  >>> [DeltaF, dDeltaF] = Gauss(w_F)
  >>> print 'Forward Gaussian approximated free energy difference is %.3f +- %.3f kT' % (DeltaF, dDeltaF)
  Forward Gaussian approximated free energy difference is 1.049 +- 0.089 kT
  >>> [DeltaF, dDeltaF] = Gauss(w_R)
  >>> print 'Reverse Gaussian approximated free energy difference is %.3f +- %.3f kT' % (DeltaF, dDeltaF)
  Reverse Gaussian approximated free energy difference is -1.073 +- 0.080 kT
  
  """

  # Get number of work measurements.
  T = float(numpy.size(w_F)) # number of work measurements
  
  var = numpy.var(w_F)
  # Estimate free energy difference by Gaussian approximation, dG = <U> - 0.5*var(U)
  DeltaF = numpy.average(w_F) - 0.5*var

  if compute_uncertainty:  
    # Compute effective number of uncorrelated samples.
    g = 1.0 # statistical inefficiency
    T_eff = T
    if is_timeseries:
      # Estimate statistical inefficiency of x timeseries.
      import timeseries
      g = timeseries.statisticalInefficiency(w_F, w_F)

      T_eff = T/g
    # Estimate standard error of E[x].
    dx2 = var/ T_eff + 0.5*var*var/(T_eff - 1)
    dDeltaF = numpy.sqrt(dx2)

    # Return estimate of free energy difference and uncertainty.
    return (DeltaF, dDeltaF)
  else:
    return DeltaF
  
#=============================================================================================
# Bennett acceptance ratio function to be zeroed to solve for BAR.
#=============================================================================================
def BARzero(w_F,w_R,DeltaF):
    """
    ARGUMENTS
      w_F (numpy.array) - w_F[t] is the forward work value from snapshot t.
                        t = 0...(T_F-1)  Length T_F is deduced from vector.
      w_R (numpy.array) - w_R[t] is the reverse work value from snapshot t.
                        t = 0...(T_R-1)  Length T_R is deduced from vector.

      DeltaF (float) - Our current guess

    RETURNS

      fzero - a variable that is zeroed when DeltaF satisfies BAR.
    """

    # Recommended stable implementation of BAR.

    # Determine number of forward and reverse work values provided.
    T_F = float(w_F.size) # number of forward work values
    T_R = float(w_R.size) # number of reverse work values

    # Compute log ratio of forward and reverse counts.
    M = numpy.log(T_F / T_R)
    
    # Compute log numerator.
    # log f(W) = - log [1 + exp((M + W - DeltaF))]
    #          = - log ( exp[+maxarg] [exp[-maxarg] + exp[(M + W - DeltaF) - maxarg]] )
    #          = - maxarg - log[exp[-maxarg] + (T_F/T_R) exp[(M + W - DeltaF) - maxarg]]
    # where maxarg = max( (M + W - DeltaF) )
    exp_arg_F = (M + w_F - DeltaF)
    max_arg_F = numpy.choose(numpy.greater(0.0, exp_arg_F), (0.0, exp_arg_F))
    log_f_F = - max_arg_F - numpy.log( numpy.exp(-max_arg_F) + numpy.exp(exp_arg_F - max_arg_F) )
    log_numer = logsum(log_f_F) - numpy.log(T_F)
    
    # Compute log_denominator.
    # log_denom = log < f(-W) exp[-W] >_R
    # NOTE: log [f(-W) exp(-W)] = log f(-W) - W
    exp_arg_R = (M - w_R - DeltaF)
    max_arg_R = numpy.choose(numpy.greater(0.0, exp_arg_R), (0.0, exp_arg_R))
    log_f_R = - max_arg_R - numpy.log( numpy.exp(-max_arg_R) + numpy.exp(exp_arg_R - max_arg_R) ) - w_R 
    log_denom = logsum(log_f_R) - numpy.log(T_R)

    # This function must be zeroed to find a root
    fzero  = DeltaF - (log_denom - log_numer)

    return fzero

def BAR(w_F, w_R, DeltaF=0.0, compute_uncertainty=True, maximum_iterations=500, relative_tolerance=1.0e-11, verbose=False, method='false-position', optimized = True):
  """
  Compute free energy difference using the Bennett acceptance ratio (BAR) method.

  ARGUMENTS
    w_F (numpy.array) - w_F[t] is the forward work value from snapshot t.
                        t = 0...(T_F-1)  Length T_F is deduced from vector.
    w_R (numpy.array) - w_R[t] is the reverse work value from snapshot t.
                        t = 0...(T_R-1)  Length T_R is deduced from vector.

  OPTIONAL ARGUMENTS

    DeltaF (float) - DeltaF can be set to initialize the free energy difference with a guess (default 0.0)
    compute_uncertainty (boolean) - if False, only the free energy is returned (default: True)
    maximum_iterations (int) - can be set to limit the maximum number of iterations performed (default 500)
    relative_tolerance (float) - can be set to determine the relative tolerance convergence criteria (defailt 1.0e-5)
    verbose (boolean) - should be set to True if verbse debug output is desired (default False)
    method - choice of method to solve BAR nonlinear equations, one of 'self-consistent-iteration' or 'false-position' (default: 'false-positions')
    optimized (bool) - whether to fully solve the optimized BAR equation to consistency, or to stop after one step, to be 
                equivalent to transition matrix sampling.
  RETURNS

    [DeltaF, dDeltaF] where dDeltaF is the estimated std dev uncertainty

  REFERENCE

    [1] Shirts MR, Bair E, Hooker G, and Pande VS. Equilibrium free energies from nonequilibrium
    measurements using maximum-likelihood methods. PRL 91(14):140601, 2003.

  NOTE

    The false position method is used to solve the implicit equation.

  EXAMPLES

  Compute free energy difference between two specified samples of work values.

  >>> import testsystems
  >>> [w_F, w_R] = testsystems.GaussianWorkSample(mu_F=None, DeltaF=1.0, seed=0)
  >>> [DeltaF, dDeltaF] = BAR(w_F, w_R)
  >>> print 'Free energy difference is %.3f +- %.3f kT' % (DeltaF, dDeltaF)
  Free energy difference is 1.088 +- 0.050 kT
    
  """

  # if computing nonoptimized, one step value, we set the max-iterations 
  # to 1, and the method to 'self-consistent-iteration'
  if not optimized:
    maximum_iterations = 1
    method = 'self-consistent-iteration'
    DeltaF_initial = DeltaF

  if method == 'self-consistent-iteration':  
    nfunc = 0

  if method == 'bisection' or method == 'false-position':
    UpperB = EXP(w_F)[0]
    LowerB = -EXP(w_R)[0]

    FUpperB = BARzero(w_F,w_R,UpperB)
    FLowerB = BARzero(w_F,w_R,LowerB)
    nfunc = 2;
    
    if (numpy.isnan(FUpperB) or numpy.isnan(FLowerB)):
      # this data set is returning NAN -- will likely not work.  Return 0, print a warning:
      print "Warning: BAR is likely to be inaccurate because of poor sampling. Guessing 0."
      if compute_uncertainty:
        return [0.0, 0.0]
      else:
        return 0.0
      
    while FUpperB*FLowerB > 0:
      # if they have the same sign, they do not bracket.  Widen the bracket until they have opposite signs.
      # There may be a better way to do this, and the above bracket should rarely fail.
      if verbose:
        print 'Initial brackets did not actually bracket, widening them'
      FAve = (UpperB+LowerB)/2
      UpperB = UpperB - max(abs(UpperB-FAve),0.1)
      LowerB = LowerB + max(abs(LowerB-FAve),0.1)
      FUpperB = BARzero(w_F,w_R,UpperB)
      FLowerB = BARzero(w_F,w_R,LowerB)
      nfunc += 2

  # Iterate to convergence or until maximum number of iterations has been exceeded.

  for iteration in range(maximum_iterations):

    DeltaF_old = DeltaF
    
    if method == 'false-position':
      # Predict the new value
      if (LowerB==0.0) and (UpperB==0.0):
        DeltaF = 0.0
        FNew = 0.0
      else:
        DeltaF = UpperB - FUpperB*(UpperB-LowerB)/(FUpperB-FLowerB)
        FNew = BARzero(w_F,w_R,DeltaF)
      nfunc += 1
     
      if FNew == 0: 
        # Convergence is achieved.
        if verbose: 
          print "Convergence achieved."
        relative_change = 10^(-15)
        break

    if method == 'bisection':
      # Predict the new value
      DeltaF = (UpperB+LowerB)/2
      FNew = BARzero(w_F,w_R,DeltaF)
      nfunc += 1
  
    if method == 'self-consistent-iteration':  
      DeltaF = -BARzero(w_F,w_R,DeltaF) + DeltaF
      nfunc += 1

    # Check for convergence.
    if (DeltaF == 0.0):
      # The free energy difference appears to be zero -- return.
      if verbose: print "The free energy difference appears to be zero."
      if compute_uncertainty:
        return [0.0, 0.0]
      else:
        return 0.0
        
    if optimized: 
      relative_change = abs((DeltaF - DeltaF_old)/DeltaF)
      if verbose:
        print "relative_change = %12.3f" % relative_change
          
      if ((iteration > 0) and (relative_change < relative_tolerance)):
        # Convergence is achieved.
        if verbose: 
          print "Convergence achieved."
        break

    if method == 'false-position' or method == 'bisection':
      if FUpperB*FNew < 0:
      # these two now bracket the root
        LowerB = DeltaF
        FLowerB = FNew
      elif FLowerB*FNew <= 0:
      # these two now bracket the root
        UpperB = DeltaF
        FUpperB = FNew
      else:
        message = 'WARNING: Cannot determine bound on free energy'
        raise BoundsError(message)        

    if verbose:
      print "iteration %5d : DeltaF = %16.3f" % (iteration, DeltaF)

  # Report convergence, or warn user if not achieved.
  if optimized: 
    if iteration < maximum_iterations:
      if verbose: 
        print 'Converged to tolerance of %e in %d iterations (%d function evaluations)' % (relative_change, iteration,nfunc)
    else:
      message = 'WARNING: Did not converge to within specified tolerance. max_delta = %f, TOLERANCE = %f, MAX_ITS = %d' % (relative_change, relative_tolerance, maximum_iterations)
      raise ConvergenceError(message)

  if compute_uncertainty:
    # Compute asymptotic variance estimate using Eq. 10a of Bennett, 1976 (except with n_1<f>_1^2 in 
    # the second denominator, it is an error in the original
    # NOTE: The numerical stability of this computation may need to be improved.

    # Determine number of forward and reverse work values provided.
    T_F = float(w_F.size) # number of forward work values
    T_R = float(w_R.size) # number of reverse work values
    # Compute log ratio of forward and reverse counts.
    M = numpy.log(T_F / T_R)

    if optimized:
      C = M-DeltaF
    else:
      C = M-DeltaF_initial

    fF =  1/(1+numpy.exp(w_F + C))
    fR =  1/(1+numpy.exp(w_R - C))
    
    afF2 = (numpy.average(fF))**2
    afR2 = (numpy.average(fR))**2
    
    vfF = numpy.var(fF)/T_F
    vfR = numpy.var(fR)/T_R

    variance = vfF/afF2 + vfR/afR2

    dDeltaF = numpy.sqrt(variance)
    if verbose: print "DeltaF = %8.3f +- %8.3f" % (DeltaF, dDeltaF)
    return (DeltaF, dDeltaF)
  else: 
    if verbose: print "DeltaF = %8.3f" % (DeltaF)
    return DeltaF

#=============================================================================================
# MBAR class definition
#=============================================================================================
class MBAR:
  """

  Multistate Bennett acceptance ratio method (MBAR) for the analysis of multiple equilibrium samples.

  NOTES

    Note that this method assumes the data are uncorrelated.
    Correlated data must be subsampled to extract uncorrelated (effectively independent) samples (see example below).

  REFERENCE

     [1] Shirts MR and Chodera JD. Statistically optimal analysis of samples from multiple equilibrium states.
     J. Chem. Phys. 129:124105, 2008
     http://dx.doi.org/10.1063/1.2978177

  EXAMPLES

  More examples and sample datasets can be obtained from http://www.simtk.org/home/pymbar

  * Example 1. Computation of relative free energies from an alchemical simulation.

  # Import the MBAR analysis code.
  import MBAR # MBAR
  import timeseries # timeseries analysis and subsampling

  # Suppose the energies sampled from each simulation are u_klt, where u_klt[k,l,t] is the reduced potential energy
  # of snapshot t \in 1,...,T_k of simulation k \in 1,...,K evaluated at reduced potential for state l.

  # First, we subsample the data to obtain statistically uncorrelated samples.
  N_k = zeros([K], int32) # N_k[k] will denote the number of correlated snapshots from state k
  u_kln = zeros([K, K, T_k.max()], numpy.float64) # u_kln[k,l,n] will store the reduced potential energy at state l of uncorrelated snapshot n \in 1..N_k[k] from state k.
  for k in range(0,K):
      # Determined indices of statistically independent configurations by analyzing the correlation structure of the timeseries data.
      indices = timeseries.subsampleCorrelatedData(u_klt[k,k,0:T_k[k]])

      # Subsample data.
      N_k[k] = len(indices)
      for l in range(0,K):
          u_kln[k,l,0:N_k[k]] = u_klt[k,l,indices]

  # Initialize MBAR with reduced energies u_kln and number of uncorrelated configurations from each state N_k.
  # 
  # u_kln[k,l,n] is the reduced potential energy beta*U_l(x_kn), where U_l(x) is the potential energy function for state l,
  # beta is the inverse temperature, and and x_kn denotes uncorrelated configuration n from state k.
  #
  # N_k[k] is the number of configurations from state k stored in u_knm
  # 
  # Note that this step may take some time, as the relative dimensionless free energies f_k are determined at this point.
  mbar = MBAR.mbar(u_kln, N_k)

  # Extract dimensionless free energy differences and their statistical uncertainties.
  (Deltaf_ij, dDeltaf_ij) = mbar.getFreeEnergyDifferences()
  print 'Unit-bearing free energy difference between states 1 and K: %f +- %f' % ( (1./beta) * Deltaf_ij[0,K-1], (1./beta) * dDeltaf_ij[0,K-1])

  # Compute the expectation of some observable A(x) at each state i, and associated uncertainty matrix.
  # Here, A_kn[k,n] = A(x_{kn})
  (A_k, dA_k) = mbar.computeExpectations(A_kn)
    
  """
  #=============================================================================================
  def __init__(self, u_kln, N_k, maximum_iterations=10000, relative_tolerance=1.0e-7, verbose=False, initial_f_k=None, method='adaptive', use_optimized=None, newton_first_gamma = 0.1,  newton_self_consistent = 2, maxrange = 1.0e5, initialize='zeros'):
    """
    Initialize multistate Bennett acceptance ratio (MBAR) on a set of simulation data.

    Upon initialization, the dimensionless free energies for all states are computed.
    This may take anywhere from seconds to minutes, depending upon the quantity of data.

    After initialization, the computed free energies may be obtained by a call to 'getFreeEnergies()', or
    free energies or expectation at any state of interest can be computed by calls to 'computeFreeEnergy()' or
    'computeExpectations()'.
    
    REQUIRED ARGUMENTS
      u_kln (KxKxNmax float array) - u_kln[k,l,n] is the reduced potential energy of uncorrelated configuration n sampled from state k, evaluated at state l
      N_k (K int array) - N_k[k] is the number of uncorrelated snapshots sampled from state k -- this can be zero if the expectation or free energy
          of this state is desired but no samples were drawn from this state

    NOTES
      The reduced potential energy u_kln[k,l,n] = u_l(x_{kn}), where the reduced potential energy u_l(x) is defined (as in the text) by:
        u_l(x) = beta_l [ U_l(x) + p_l V(x) + mu_l' n(x) ]
      where
        beta_l = 1/(kB T_l) is the inverse temperature of condition l, where kB is Boltzmann's constant
        U_l(x) is the potential energy function for state l
        p_l is the pressure at state l (if an isobaric ensemble is specified)
        V(x) is the volume of configuration x
        mu_l is the M-vector of chemical potentials for the various species, if a (semi)grand ensemble is specified, and ' denotes transpose
        n(x) is the M-vector of numbers of the various molecular species for configuration x, corresponding to the chemical potential components of mu_m.

      The configurations x_kn must be uncorrelated.  This can be ensured by subsampling a correlated timeseries with a period larger than the statistical inefficiency,
      which can be estimated from the potential energy timeseries {u_k(x_kn)}_{n=1}^{N_k} using the provided utility function 'statisticalInefficiency()'.
      See the help for this function for more information.

    OPTIONAL ARGUMENTS
      maximum_iterations (int) - can be set to limit the maximum number of iterations performed (default 1000)
      relative_tolerance (float) - can be set to determine the relative tolerance convergence criteria (default 1.0e-6)
      verbosity (logical) - should be set to True if verbose debug output is desired (default False)
      initial_f_k (numpy K float64 array) - should be set to a numpy K-array with initial dimensionless free energies to use as a guess (default None, which sets all f_k = 0)
      method (string) - choose method for determination of dimensionless free energies: 'self-consistent-iteration','Newton-Raphson','matrix-iteration', or 'adaptive' (default: 'adaptive')
        Newton-Raphson starts with one iteration of self-consistent-iteration as a safeguard in case initial guess at f_k is in a highly non-quadratic region        
      use_optimized - if False, will explicitly disable use of C++ extensions; if None or True, extensions will be autodetected (default: None)
      initialize (string) - option for initialization.  if equal to 'BAR', use BAR between the pairwise state to initialize the free energies.  Eventually, should specify a path; for now, it just does it zipping up the states. (default: 'zeros', unless specific values are passed in.)
      newton_first_gamma (float) - initial gamma for newton-raphson (default = 0.1)
      newton_self_consistent (int) - mininum number of self-consistent iterations before Newton-Raphson iteration (default = 2)


    TEST

    >>> import testsystems
    >>> [x_kn, u_kln, N_k] = testsystems.HarmonicOscillatorsSample()
    >>> mbar = MBAR(u_kln, N_k)

    """

    # CHECKME: Do we want to keep BARinitialize?  Does it really help speed convergence?

    # Determine whether embedded C++ helper code is available
    self.use_embedded_helper_code = False
    if (use_optimized != None):
      # If user specifies an option, use this.
      self.use_embedded_helper_code = use_optimized
    else:
      # Test whether we can import the helper code.
      try:
        import _pymbar # import the helper code
        self.use_embedded_helper_code = True # if we have succeeded, use it
        if verbose: print "Using embedded C++ helper code."
      except ImportError:
        # import failed
        self.use_embedded_helper_code = False
        if verbose: print "Could not import working embedded C++ helper code -- using pure Python version instead."
              
    # Store local copies of necessary data.
    self.N_k = numpy.array(N_k, dtype=numpy.int32) # N_k[k] is the number of samples from state k
    self.u_kln = numpy.array(u_kln, dtype=numpy.float64) # u_kln[k,l,n] is the reduced potential energy of sample n from state k evaluated at state l

    # Get dimensions of reduced potential energy matrix.
    [K, L, N_max] = self.u_kln.shape    
    if verbose: print "K = %d, L = %d, N_max = %d, total samples = %d" % (K, L, N_max, self.N_k.sum())

    # Perform consistency checks on dimensions.
    if K != L:
      raise ParameterError('u_kln[0:K, 0:L, 0:N_max] must have dimensions K == L.')
    if numpy.any(N_k > N_max):
      raise ParameterError('All N_k must be <= N_max, the third dimension of u_kln[0:K, 0:L, 0:N_max].')

    # Store local copies of other data
    self.K = K # number of thermodynamic states
    self.N_max = N_max # maximum number of configurations per state
    self.N = sum(self.N_k) # N = \sum_{k=1}^K N_k is the total number of uncorrelated configurations pooled across all states
    self.verbose = verbose # verbosity level -- if True, will print extra debug information

    # perform consistency checks on the data.  

    # if, for any set of data, all reduced potential energies are the same, 
    # they are probably the same state.  We check to within relative_tolerance.

    self.samestates = []
    for k in range(K):
      for l in range(k):
        diffsum = 0
        for j in range(K): # find the nonzero sets of data: 
          if (self.N_k[j] > 0):
            uzero = u_kln[j,k,:] - u_kln[j,l,:]
            diffsum += numpy.dot(uzero,uzero);
        if (diffsum < relative_tolerance):
          self.samestates.append([k,l])
          self.samestates.append([l,k])
          print ''
          print 'Warning: states %d and %d have the same energies on the dataset.' % (l,k)
          print 'They are therefore likely to to be the same thermodynamic state.  This can occasionally cause'
          print 'numerical problems with computing the covariance of their energy difference, which must be'
          print 'identically zero in any case. Consider combining them into a single state.' 
          print ''

    # Create a list of indices of all configurations in kn-indexing.
    mask_kn = numpy.zeros([self.K,self.N_max], dtype=numpy.bool_)
    for k in range(0,self.K):
      mask_kn[k,0:N_k[k]] = True
    # Create a list from this mask.
    self.indices = numpy.where(mask_kn)

    # Determine list of k indices for which N_k != 0
    self.nonzero_N_k_indices = numpy.where(self.N_k != 0)[0]
    self.nonzero_N_k_indices = self.nonzero_N_k_indices.astype(numpy.int32)
    
    # Store versions of variables nonzero indices file
    # Number of states with samples.
    self.K_nonzero = self.nonzero_N_k_indices.size
    if verbose:
      print "There are %d states with samples." % self.K_nonzero

    self.N_nonzero = self.N_k[self.nonzero_N_k_indices].copy()

    # Print number of samples from each state.
    if self.verbose:
      print "N_k = "
      print N_k

    # Initialize estimate of relative dimensionless free energy of each state to zero.
    # Note that f_k[0] will be constrained to be zero throughout.
    # this is default  
    self.f_k = numpy.zeros([self.K], dtype=numpy.float64)

    # If an initial guess of the relative dimensionless free energies is specified, start with that.
    if initial_f_k != None:
      if self.verbose: print "Initializing f_k with provided initial guess."
      # Cast to numpy array.
      initial_f_k = numpy.array(initial_f_k, dtype=numpy.float64)
      # Check shape
      if initial_f_k.shape != self.f_k.shape:
        raise ParameterError("initial_f_k must be a %d-dimensional numpy array." % self.K)
      # Initialize f_k with provided guess.
      self.f_k = initial_f_k
      if self.verbose: print self.f_k
      # Shift all free energies such that f_0 = 0.
      self.f_k[:] = self.f_k[:] - self.f_k[0]
    else:
      # Initialize estimate of relative dimensionless free energies.
      self._initializeFreeEnergies(verbose,method=initialize)

      if self.verbose:
        print "Initial dimensionless free energies with method %s" % (initialize)
        print "f_k = "
        print self.f_k      

    # Solve nonlinear equations for free energies of states with samples.
    if (maximum_iterations > 0):
      # Determine dimensionles free energies.    
      if method == 'self-consistent-iteration':
        # Use self-consistent iteration of MBAR equations.
        self._selfConsistentIteration(maximum_iterations = maximum_iterations, relative_tolerance = relative_tolerance, verbose = verbose)      
      elif method == 'Newton-Raphson':         
        # Use Newton-Raphson, starting with self-consistent iteration for a couple steps.
          self._selfConsistentIteration(maximum_iterations = newton_self_consistent, relative_tolerance = relative_tolerance, verbose = verbose, print_warning=False)
          self._NewtonRaphson(first_gamma = newton_first_gamma, maximum_iterations = maximum_iterations, relative_tolerance = relative_tolerance, verbose = verbose)
      elif method == 'adaptive': # take both steps at each point, choose 'best' by minimum gradient
        self._adaptive(maximum_iterations = maximum_iterations, relative_tolerance = relative_tolerance, verbose = verbose,print_warning=False)        
      else:    
        raise ParameterError("Specified method = '%s' is not a valid method. Specify 'self-consistent-iteration','Newton-Raphson', or 'adaptive'.")    
      
    # Recompute all free energies because those from states with zero samples are not correctly computed by Newton-Raphson.
    # and store the log weights
    if verbose: 
      print "Recomputing all free energies and log weights for storage"
    (self.Log_W_nk,self.f_k) = self._computeWeights(recalc_denom=False,logform=True,include_nonzero=True,return_f_k=True)  

    # Print final dimensionless free energies.
    if self.verbose:
      print "Final dimensionless free energies"
      print "f_k = "
      print self.f_k      

    if self.verbose: print "MBAR initialization complete."
    return

  #=============================================================================================
  def getWeights(self):
    """
    Retrieve the weight matrix W_nk from the MBAR algorithm, since they are stored internally as log weights
    
    ARGUMENTS
    
       None

    RETURNS

    NxK matrix of weights in the MBAR covariance and averaging formulas 

    """

    return numpy.exp(self.Log_W_nk)

  #=============================================================================================
  def getFreeEnergyDifferences(self, compute_uncertainty=True, uncertainty_method=None, warning_cutoff=1.0e-10):
    """
    Retrieve the dimensionless free energy differences and associated uncertainties among all thermodynamic states.


    RETURNS
    
      Deltaf_ij (KxK numpy float64 array) - Deltaf_ij[i,j] = f_j - f_i, the dimensionless free energy difference between states i and j
      dDeltaf_ij (KxK numpy float64 array) - dDeltaf_ij[i,j] is the estimated statistical uncertainty (one standard deviation) in Deltaf_ij[i,j]

    OPTIONAL ARGUMENTS
      compute_uncertainty (boolean) - if set to False, the uncertainties will not be computed (default: True)
      uncertainty_method (string) - choice of method used to compute asymptotic covariance method, or None to use default
                        See help for computeAsymptoticCovarianceMatrix() for more information on various methods. (default: svd)
      warning_cutoff (float) - warn if squared-uncertainty is negative and larger in magnitude than this number (default: 1.0e-10)

    NOTES
      Computation of the covariance matrix may take some time for large K.

      The reported statistical uncertainty should, in the asymptotic limit, reflect one standard deviation for the normal distribution of the estimate.
      The true free energy difference should fall within the interval [-df, +df] centered on the estimate 68% of the time, and within
      the interval [-2 df, +2 df] centered on the estimate 95% of the time.
      This will break down in cases where the number of samples is not large enough to reach the asymptotic normal limit.

    REFERENCE
      See Section III of Reference [1].

    TEST

    >>> import testsystems
    >>> [x_kn, u_kln, N_k] = testsystems.HarmonicOscillatorsSample()
    >>> mbar = MBAR(u_kln, N_k)
    >>> [Deltaf_ij, dDeltaf_ij] = mbar.getFreeEnergyDifferences()
    
    """

    # Compute free energy differences.
    f_i = numpy.matrix(self.f_k).repeat(repeats=self.K,axis=0)
    Deltaf_ij = f_i - f_i.transpose()

    # zero out numerical error for thermodynamically identical states
    self._zerosamestates(Deltaf_ij)

    if compute_uncertainty:
      # Compute asymptotic covariance matrix.
      Theta_ij = self._computeAsymptoticCovarianceMatrix(numpy.exp(self.Log_W_nk), self.N_k, method=uncertainty_method)    

      # compute the covariance component without doing the double loop.
      # d2DeltaF = Theta_ij[i,i] + Theta_ij[j,j] - 2.0 * Theta_ij[i,j]           

      diag = Theta_ij.diagonal()
      dii = diag.repeat(repeats=self.K,axis=0)
      d2DeltaF = dii+dii.transpose()-2*Theta_ij 

      # zero out numerical error for thermodynamically identical states
      self._zerosamestates(d2DeltaF)

      # check for any numbers below zero.
      if (numpy.any(d2DeltaF<0.0)):
        if(numpy.any(d2DeltaF) < warning_cutoff):
          # Hmm.  Will this print correctly?
          print "A squared uncertainty is negative.  d2DeltaF = %e" % d2DeltaF[(numpy.any(d2DeltaF)< warning_cutoff)]
        else:
          d2DeltaF[(numpy.any(d2DeltaF)< warning_cutoff)] = 0.0

      # take the square root of the matrix   
      dDeltaf_ij = numpy.sqrt(d2DeltaF)

      # Return matrix of free energy differences and uncertainties.
      return (Deltaf_ij, dDeltaf_ij)
    else:
      # Return only free energy differences.
      return Deltaf_ij    

  #=============================================================================================

  def computeExpectations(self, A_kn, uncertainty_method=None, output='averages'):
    """
    Compute the expectation of an observable of phase space function A(x) at all K states, including states for which no samples were drawn. A may be a function of the state k.

    REQUIRED ARGUMENTS
      Two possibilities, depending on if the observable is a function of the state or not.
      either: not dependent on the state
         A_kn (KxN_max numpy float64 array) - A_kn[k,n] = A(x_kn)
      or: dependent on state
         A_kn (KxKxN_max numpy float64 array) - A_kn[k,l,n] = A(x_kn)
      where the 2nd dimension is the observable as a function of the state

    OPTIONAL ARUMENTS
      uncertainty_method (string) - choice of method used to compute asymptotic covariance method, or None to use default
                        See help for computeAsymptoticCovarianceMatrix() for more information on various methods. (default: None)
      output (string) - either output averages, and uncertainties, or output a matrix of differences, with uncertainties.

    RETURN VALUES
      if output is 'averages'
         A_i  (K numpy float64 array) -  A_i[k] is the estimate for the expectation of A(x) for state k.
        dA_i  (K numpy float64 array) - dA_i[k] is uncertainty estimate (one standard deviation) for A_k[k]
      if output is 'differences'
         A_ij (K numpy float64 array) -  A_ij[i,j] is the difference in the estimates for the expectation of A(x).
        dA_ij (K numpy float64 array) - dA_ij[i,j] is uncertainty estimate (one standard deviation) for the difference in A beteen i and j

    NOTES

      The reported statistical uncertainty should, in the asymptotic limit, reflect one standard deviation for the normal distribution of the estimate.
      The true expectation should fall within the interval [-dA, +dA] centered on the estimate 68% of the time, and within
      the interval [-2 dA, +2 dA] centered on the estimate 95% of the time.
      This will break down in cases where the number of samples is not large enough to reach the asymptotic normal limit.
      This 'breakdown' can be exacerbated by the computation of observables like indicator functions for histograms that are sparsely populated.

    REFERENCE
      See Section IV of [1].

    TEST

    >>> import testsystems
    >>> [x_kn, u_kln, N_k] = testsystems.HarmonicOscillatorsSample()
    >>> mbar = MBAR(u_kln, N_k)
    >>> A_kn = x_kn
    >>> [A_ij, dA_ij] = mbar.computeExpectations(A_kn)
    >>> A_kn = u_kln
    >>> [A_ij, dA_ij] = mbar.computeExpectations(A_kn, output='differences')
    """

    # Convert to numpy matrix.
    A_kn = numpy.array(A_kn, numpy.float64)

    # Retrieve N and K for convenience.
    N = self.N
    K = self.K

    dim = len(numpy.shape(A_kn))

    # Augment W_nk, N_k, and c_k for q_A(x) for the observable, with one extra row/column for each state (Eq. 13 of [1]).
    Log_W_nk = numpy.zeros([N, K*2], numpy.float64) # log of weight matrix
    N_k = numpy.zeros([K*2], numpy.int32) # counts
    f_k = numpy.zeros([K], numpy.float64) # "free energies" of the new states 

    # Fill in first half of matrix with existing q_k(x) from states.
    Log_W_nk[:,0:K] = self.Log_W_nk
    N_k[0:K] = self.N_k

    # Compute the remaining rows/columns of W_nk and the rows c_k for the observables.

    A_i = numpy.zeros([K], numpy.float64)
    A_min = numpy.min(A_kn)
    A_kn = A_kn-(A_min-1) # numerical trick to keep them all positive for logarithms

    if (dim == 2): 
      # Convert A_kn to n = 1..N indexing.
      A_n = A_kn[self.indices]

    for l in range(0,K):
      if (dim == 3):
        A_nkstate = A_kn[:,l,:]
        A_n = A_nkstate[self.indices]

      Log_W_nk[:,K+l] = numpy.log(A_n) + self.Log_W_nk[:,l] # this works because all A_n are now positive;
                                                            # we took the min at the beginning.
      f_k[l] = -logsum(Log_W_nk[:,K+l])
      Log_W_nk[:,K+l] += f_k[l]              # normalize the row   
      A_i[l] = numpy.exp(-f_k[l])
      
    # Compute augmented asymptotic covariance matrix.
    W_nk = numpy.exp(Log_W_nk)
    Theta_ij = self._computeAsymptoticCovarianceMatrix(W_nk, N_k, method = uncertainty_method)

    if (output == 'averages'):

      # Compute estimators and uncertainties.
      dA_i = numpy.zeros([K], numpy.float64)    
      for k in range(0,K):
        dA_i[k] = abs(A_i[k]) * numpy.sqrt(Theta_ij[K+k,K+k] + Theta_ij[k,k] - 2.0 * Theta_ij[k,K+k]) # Eq. 16 of [1]

      # add back minima now now that uncertainties are computed.
      A_i += (A_min-1)
      # Return expectations and uncertainties.
      return (A_i, dA_i)

    if (output == 'differences'):

      # Return differences of expectations and uncertainties.

      A_ij = numpy.zeros([K,K], dtype=numpy.float64)
      dA_ij = numpy.zeros([K,K], dtype=numpy.float64)        
      
      for i in range(0,K):
        for j in range(0,K):

          # Compute expectation difference.
          A_ij[i,j] = A_i[j] - A_i[i]
          try:
            dA_ij[i,j] = math.sqrt(
            + A_i[i] * Theta_ij[i,i]   * A_i[i] - A_i[i] * Theta_ij[i,j]   * A_i[j] - A_i[i] * Theta_ij[i,K+i]   * A_i[i] + A_i[i] * Theta_ij[i,K+j]   * A_i[j]
            - A_i[j] * Theta_ij[j,i]   * A_i[i] + A_i[j] * Theta_ij[j,j]   * A_i[j] + A_i[j] * Theta_ij[j,K+i]   * A_i[i] - A_i[j] * Theta_ij[j,K+j]   * A_i[j]
            - A_i[i] * Theta_ij[K+i,i] * A_i[i] + A_i[i] * Theta_ij[K+i,j] * A_i[j] + A_i[i] * Theta_ij[K+i,K+i] * A_i[i] - A_i[i] * Theta_ij[K+i,K+j] * A_i[j]
            + A_i[j] * Theta_ij[K+j,i] * A_i[i] - A_i[j] * Theta_ij[K+j,j] * A_i[j] - A_i[j] * Theta_ij[K+j,K+i] * A_i[i] + A_i[j] * Theta_ij[K+j,K+j] * A_i[j]
            )
          except:
            dA_ij[i,j] = 0.0

      return (A_ij,dA_ij)
      
  #=============================================================================================
  def computeMultipleExpectations(self, A_ikn, u_kn, uncertainty_method=None):
    """Compute the expectations of multiple observables of phase space functions [A_0(x),A_1(x),...,A_n(x)] 
       at single specified state, along with the covariances of their estimates.  The state is specified by 
       the choice of u_kn, which is the energy of the kxn samples evaluated at the chosen state.  Note that 
       these variables A should not be functions of the state!

    REQUIRED ARGUMENTS
      A_ikn (IxKxN_max numpy float64 array) - A_ikn[i,k,n] = A_i(x_kn), the value of phase observable i for configuration n at state k
      u_kn (KxN_max numpy float64 array) - u_kn[k,n] is the reduced potential of configuration n gathered from state k, at the state of interest

    OPTIONAL ARUMENTS
      uncertainty_method (string) - choice of method used to compute asymptotic covariance method, or None to use default
                        See help for computeAsymptoticCovarianceMatrix() for more information on various methods. (default: None)

    RETURN VALUES
      A_i (I numpy float64 array) - A_i[i] is the estimate for the expectation of A_i(x) at the state specified by u_kn
      d2A_ij (IxI numpy float64 array) - d2A_ij[i,j] is the COVARIANCE in the estimates of A_i[i] and A_i[j],
      not the square root of the covariance 

    NOTE: Not fully tested.

    TESTS

    >>> import testsystems
    >>> [x_kn, u_kln, N_k] = testsystems.HarmonicOscillatorsSample()
    >>> mbar = MBAR(u_kln, N_k)
    >>> A_ikn = numpy.array([x_kn,x_kn**2,x_kn**3])
    >>> u_kn = u_kln[:,0,:]
    >>> [A_i, d2A_ij] = mbar.computeMultipleExpectations(A_ikn, u_kn)
    
    """
    
    # Retrieve N and K for convenience.
    I = A_ikn.shape[0] # number of observables
    K = self.K
    N = self.N # N is total number of samples

    # Convert A_kn to n = 1..N indexing.
    A_in = numpy.zeros([I, N], numpy.float64)
    A_min = numpy.zeros([I],dtype=numpy.float64)  
    for i in range(I):
      A_kn = numpy.array(A_ikn[i,:,:])
      A_in[i,:] = A_kn[self.indices]
      A_min[i] = numpy.min(A_in[i,:]) #find the minimum
      A_in[i,:] -= (A_min[i]-1)  #all now values will be positive so that we can work in logarithmic scale

    # Augment W_nk, N_k, and c_k for q_A(x) for the observables, with one row for the specified state and I rows for the observable at that state.
    Log_W_nk = numpy.zeros([N, K+1+I], numpy.float64) # log weight matrix
    W_nk = numpy.zeros([N, K+1+I], numpy.float64) # weight matrix    
    N_k = numpy.zeros([K+1+I], numpy.int32) # counts
    f_k = numpy.zeros([K+1+I], numpy.float64) # free energies

    # Fill in first section of matrix with existing q_k(x) from states.
    Log_W_nk[:,0:K] = self.Log_W_nk
    W_nk[:,0:K] = numpy.exp(self.Log_W_nk)
    N_k[0:K] = self.N_k
    f_k[0:K] = self.f_k

    # Compute row of W matrix for the extra state corresponding to u_kn.
    Log_w_kn = self._computeUnnormalizedLogWeights(u_kn)
    Log_W_nk[:,K] = Log_w_kn[self.indices] 
    f_k[K] = -logsum(Log_W_nk[:,K])
    Log_W_nk[:,K] += f_k[K]
    
    # Compute the remaining rows/columns of W_nk and c_k for the observables.
    for i in range(I):
      Log_W_nk[:,K+1+i] = numpy.log(A_in[i,:]) + Log_W_nk[:,K]
      f_k[K+1+i] = -logsum(Log_W_nk[:,K+1+i])  
      Log_W_nk[:,K+1+i] += f_k[K+1+i]    # normalize this row

    # Compute estimates.
    A_i = numpy.zeros([I], numpy.float64)
    for i in range(I):
      A_i[i] = numpy.exp(-f_k[K+1+i])

    # Compute augmented asymptotic covariance matrix.
    W_nk = numpy.exp(Log_W_nk)  
    Theta_ij = self._computeAsymptoticCovarianceMatrix(W_nk, N_k, method=uncertainty_method)

    # Compute estimates of statistical covariance
    # these variances will be the same whether or not we subtract a different constant from each A_i
    d2A_ij = numpy.zeros([I,I], numpy.float64)    
    for i in range(I):
      for j in range(I):
        d2A_ij[i,j] = A_i[i] * A_i[j] * (Theta_ij[K+1+i,K+1+j] - Theta_ij[K+1+i,K] - Theta_ij[K,K+1+j] + Theta_ij[K,K])

    # Now that variances are computed, add the constants back to A_i that were required to enforce positivity
    A_i += (A_min-1)
        
    # Return expectations and uncertainties.
    return (A_i, d2A_ij)

  #=============================================================================================      
  def computeOverlap(self,output = 'scalar'):
     """
     Compute estimate of overlap matrix between the states.
     
     RETURNS

       O (numpy.array of numpy.float64 of dimension [K,K]) - estimated state overlap matrix
         O[i,j] is an estimate of the probability of observing a sample from state i in state j
     
     OPTIONAL ARGUMENTS
     
       output (string): One of 'scalar', 'matrix', 'eigenvalues', 'all', specifying what measure
       of overlap to return

     NOTES
 
     W.T * W \approx \int (p_i p_j /\sum_k N_k p_k)^2 \sum_k N_k p_k dq^N
                   = \int (p_i p_j /\sum_k N_k p_k) dq^N

     Multiplying elementwise by N_i, the elements of row i give the probability 
     for a sample from state i being observed in state j.
     
     TEST

     >>> import testsystems
     >>> [x_kn, u_kln, N_k] = testsystems.HarmonicOscillatorsSample()
     >>> mbar = MBAR(u_kln, N_k)
     >>> O_ij = mbar.computeOverlap()
     
     """

     W = numpy.matrix(self.getWeights(), numpy.float64)
     O = numpy.multiply(self.N_k, W.T*W)
     (eigenval,eigevec) = numpy.linalg.eig(O)
     eigenval = numpy.sort(eigenval)[::-1]             # sort in descending order
     overlap_scalar = 1-eigenval[1];
     if (output == 'scalar'):
       return overlap_scalar
     elif (output == 'eigenvalues'):
       return eigenval
     elif (output == 'matrix'):
       return O
     elif (output == 'all'):
       return overlap_scalar,eigenval,O

  #=============================================================================================
  def computePerturbedExpectation(self, u_kn, A_kn, uncertainty_method=None):
    """
    Compute the expectation of an observable of phase space function A(x) for a single new state.

    REQUIRED ARGUMENTS
      u_kn (KxN_max numpy float64 array) - u_kn[k,n] = u(x_kn)
      A_kn (KxN_max numpy float64 array) - A_kn[k,n] = A(x_kn)

    OPTINAL ARUMENTS
      uncertainty_method (string) - choice of method used to compute asymptotic covariance method, or None to use default
                        See help for computeAsymptoticCovarianceMatrix() for more information on various methods. (default: None)

    RETURN VALUES
      A (double) - A is the estimate for the expectation of A(x) for the specified state
      dA (double) - dA is uncertainty estimate for A

    REFERENCE
      See Section IV of [1].
    """
    """
    Not sure this works for observables that are a function of the state.  Will need to test a bit more.
    Commenting out until then.
    """
    """
    # Convert to numpy matrix.
    A_kn = numpy.array(A_kn, dtype=numpy.float64)

    # Retrieve N and K for convenience.
    N = self.N
    K = self.K

    # Convert A_kn to n = 1..N indexing.
    A_n = A_kn[self.indices]    


    # Augment W_nk, N_k, and c_k for q_A(x) for the observable, with one extra row/column for the specified state (Eq. 13 of [1]).
    f_k = numpy.zeros([K+2], dtype=numpy.float64) # free energies
    W_nk = numpy.zeros([N, K+2], dtype=numpy.float64) # weight matrix
    N_k = numpy.zeros([K+2], dtype=numpy.int32) # counts

    # Fill in first K states with existing q_k(x) from states.
    W_nk[:,0:K] = numpy.exp(self.Log_W_nk)
    N_k[0:K] = self.N_k

    # Compute the remaining rows/columns of W_nk and c_k for the observable.

    # Compute unnormalized log weights for new state.
    log_w_kn = self._computeUnnormalizedLogWeights(u_kn)
    # Compute free energies
    f_k[K] = - logsum(log_w_kn[self.indices])
    # Store normalized weights.
    W_nk[:,K] = numpy.exp(log_w_kn[self.indices] + f_k[K])
    
    # Compute unnormalized weights for observable.
    # A(x_n) q_k(x_n) / \sum_{k'=1}^K N_{k'} exp[f_{k'} - q_{k'}(x_n)]      
    # TODO: Make this more stable to under/overflow.
    W_nk[:,K+1] = A_n[:] * W_nk[:,K]
    # Compute normalization constant from unnormalized weights
    c_k = sum(W_nk[:,K+1])
    # Normalize weights
    W_nk[:,K+1] /= c_k
           
    # Compute augmented asymptotic covariance matrix.
    Theta_ij = self._computeAsymptoticCovarianceMatrix(W_nk, N_k, method = uncertainty_method)

    # Compute estimators and uncertainty.
    A = sum(W_nk[:,K] * A_n[:]) # Eq. 15 of [1]
    dA = abs(A) * numpy.sqrt(Theta_ij[K,K] + Theta_ij[K+1,K+1] - 2.0 * Theta_ij[K,K+1]) # Eq. 16 of [1]
        
    # Return expectations and uncertainties.
    return (A, dA)
    """ 
  #=============================================================================================

  def computePerturbedFreeEnergies(self, u_kln, uncertainty_method=None, warning_cutoff=1.0e-10):
    """
    Compute the free energies for a new set of states.
    Here, we desire the free energy differences among a set of new states, as well as the uncertainty estimates in these differences.

    REQUIRED ARGUMENTS
      u_kln (KxLxNmax float array) - u_kln[k,l,n] is the reduced potential energy of uncorrelated configuration n sampled from state k, evaluated at new state l.
        L need not be the same as K.

    OPTINAL ARUMENTS
      uncertainty_method (string) - choice of method used to compute asymptotic covariance method, or None to use default
                        See help for computeAsymptoticCovarianceMatrix() for more information on various methods. (default: None)
      warning_cutoff (float) - warn if squared-uncertainty is negative and larger in magnitude than this number (default: 1.0e-10)
      
    RETURN VALUES
      Deltaf_ij (LxL numpy float64 array) - Deltaf_ij[i,j] = f_j - f_i, the dimensionless free energy difference between new states i and j
      dDeltaf_ij (LxL numpy float64 array) - dDeltaf_ij[i,j] is the estimated statistical uncertainty in Deltaf_ij[i,j]

    TEST
      
    >>> import testsystems
    >>> [x_kn, u_kln, N_k] = testsystems.HarmonicOscillatorsSample()
    >>> mbar = MBAR(u_kln, N_k)
    >>> [Deltaf_ij, dDeltaf_ij] = mbar.computePerturbedFreeEnergies(u_kln)

    """

    # Convert to numpy matrix.
    u_kln = numpy.array(u_kln, dtype=numpy.float64)

    # Get the dimensions of the matrix of reduced potential energies.
    [K, L, N_max] = u_kln.shape

    # Check dimensions.
    if (K != self.K):
      raise "K-dimension of u_kln must be the same as K-dimension of original states."
    if (N_max < self.N_k.max()):
      raise "There seems to be too few samples in u_kln."

    # Retrieve N and K for convenience.
    N = self.N
    K = self.K

    # Augment W_nk, N_k, and c_k for the new states.
    W_nk = numpy.zeros([N, K + L], dtype=numpy.float64) # weight matrix
    N_k = numpy.zeros([K + L], dtype=numpy.int32) # counts
    f_k = numpy.zeros([K + L], dtype=numpy.float64) # free energies

    # Fill in first half of matrix with existing q_k(x) from states.
    W_nk[:,0:K] = numpy.exp(self.Log_W_nk)
    N_k[0:K] = self.N_k
    f_k[0:K] = self.f_k

    # Compute normalized weights.
    for l in range(0,L):
      # Compute unnormalized log weights.
      log_w_kn = self._computeUnnormalizedLogWeights(u_kln[:,l,:])
      # Compute free energies
      f_k[K+l] = - logsum(log_w_kn[self.indices])
      # Store normalized weights.
      W_nk[:,K+l] = numpy.exp(log_w_kn[self.indices] + f_k[K+l])

    # Compute augmented asymptotic covariance matrix.
    if (uncertainty_method == None):
      Theta_ij = self._computeAsymptoticCovarianceMatrix(W_nk, N_k)
    else:
      Theta_ij = self._computeAsymptoticCovarianceMatrix(W_nk, N_k, method = uncertainty_method)

    # Compute matrix of free energy differences between states and associated uncertainties.
    Deltaf_ij = numpy.zeros([L, L], dtype=numpy.float64)
    dDeltaf_ij = numpy.zeros([L, L], dtype=numpy.float64)
    for i in range(0, L):
      for j in range(0, L):
        if i != j:
          # Compute dimensionless free energy difference and associated uncertainty (Eq. 14 of [1]).
          Deltaf_ij[i,j] = (f_k[K+j] - f_k[K+i])

          # Compute associated squared-uncertainty (estimated variance of estimate of expectation).
          d2DeltaF = Theta_ij[K+i,K+i] + Theta_ij[K+j,K+j] - 2.0 * Theta_ij[K+i,K+j]           

          # Throw an error if squared uncertainty is large and negative -- otherwise, correct to zero.
          if (d2DeltaF < 0.0):
            if(-d2DeltaF > warning_cutoff):
              print "Squared uncertainty is negative.  d2DeltaF = %e" % d2DeltaF
            else:
              d2DeltaF = 0.0
          # Compute uncertainty from squared uncertainty.
          # TODO: What should do we do if d2DeltaF < 0 here?  Is there a proper behavior if we can compute Deltaf_ij, but not the uncertainty estimate?
          if (d2DeltaF < 0.0):
            print "squared uncertainty is negative: d2Deltaf_ij[%d,%d] = %f" % (i,j,d2DeltaF)
          else:
            dDeltaf_ij[i,j] = math.sqrt( d2DeltaF )          

    # Return matrix of free energy differences and uncertainties.
    return (Deltaf_ij, dDeltaf_ij)

  #=============================================================================================
  # EXPERIMENTAL METHODS FOLLOW - USE AT YOUR OWN RISK!
  #=============================================================================================
  def computeEntropyAndEnthalpy(self, uncertainty_method=None, verbose=False):
    """
    Compute the decomposition of the free energy difference between states 1 and N into reduced free energy differences, reduced potential (enthalpy) differences, and reduced entropy (S/k) differences.

    OPTINAL ARUMENTS
      uncertainty_method (string) - choice of method used to compute asymptotic covariance method, or None to use default
                        See help for computeAsymptoticCovarianceMatrix() for more information on various methods. (default: None)

    RETURN VALUES
      Delta_f_ij (KxK numpy float matrix) - Delta_f_ij[i,j] is the dimensionless free energy difference f_j - f_i
      dDelta_f_ij (KxK numpy float matrix) - uncertainty in Delta_f_ij
      Delta_u_ij (KxK numpy float matrix) - Delta_u_ij[i,j] is the reduced potential energy difference u_j - u_i
      dDelta_u_ij (KxK numpy float matrix) - uncertainty in Delta_f_ij
      Delta_s_ij (KxK numpy float matrix) - Delta_s_ij[i,j] is the reduced entropy difference S/k between states i and j (s_j - s_i)
      dDelta_s_ij (KxK numpy float matrix) - uncertainty in Delta_s_ij

    WARNING
      This method is EXPERIMENTAL and should be used at your own risk.

    TEST
      
    >>> import testsystems
    >>> [x_kn, u_kln, N_k] = testsystems.HarmonicOscillatorsSample()
    >>> mbar = MBAR(u_kln, N_k)
    >>> [Delta_f_ij, dDelta_f_ij, Delta_u_ij, dDelta_u_ij, Delta_s_ij, dDelta_s_ij] = mbar.computeEntropyAndEnthalpy()

    """

    if verbose:
      print "Computing average energy and entropy by MBAR."

    # Retrieve N and K for convenience.
    N = self.N
    K = self.K

    # Augment W_nk, N_k, and c_k for q_A(x) for the potential energies, with one extra row/column for each state.
    Log_W_nk = numpy.zeros([N, K*2], dtype=numpy.float64) # weight matrix
    N_k = numpy.zeros([K*2], dtype=numpy.int32) # counts
    f_k = numpy.zeros(K,dtype=numpy.float64) # "free energies" of average states

    # Fill in first half of matrix with existing q_k(x) from states.
    Log_W_nk[:,0:K] = self.Log_W_nk
    N_k[0:K] = self.N_k
    
    # Compute the remaining rows/columns of W_nk and c_k for the potential energy observable.

    u_min = self.u_kln.min()
    u_i = numpy.zeros([K], dtype=numpy.float64)    
    for l in range(0,K):
      # Convert potential energies to n = 1..N indexing.
      u_kn = self.u_kln[:,l,:] - (u_min-1)  # all positive now!  Subtracting off arbitrary constants doesn't affect results. 
                                            # since they are all differences. 
      # Compute unnormalized weights.
      # A(x_n) exp[f_{k} - q_{k}(x_n)] / \sum_{k'=1}^K N_{k'} exp[f_{k'} - q_{k'}(x_n)]      
      # harden for over/underflow with logarithms

      Log_W_nk[:,K+l] = numpy.log(u_kn[self.indices]) + self.Log_W_nk[:,l] 

      f_k[l] = -logsum(Log_W_nk[:,K+l])
      Log_W_nk[:,K+l] += f_k[l]              # normalize the row      
      u_i[l] = numpy.exp(-f_k[l])

      #print "MBAR u_i[%d]: %10.5f,%10.5f" % (l,u_i[l]+u_min, u_i[l])

    # Compute augmented asymptotic covariance matrix.
    W_nk = numpy.exp(Log_W_nk)  
    Theta_ij = self._computeAsymptoticCovarianceMatrix(W_nk, N_k, method=uncertainty_method)

    # Compute estimators and uncertainties.
    Delta_f_ij = numpy.zeros([K,K], dtype=numpy.float64)
    dDelta_f_ij = numpy.zeros([K,K], dtype=numpy.float64)

    Delta_u_ij = numpy.zeros([K,K], dtype=numpy.float64)
    dDelta_u_ij = numpy.zeros([K,K], dtype=numpy.float64)        

    Delta_s_ij = numpy.zeros([K,K], dtype=numpy.float64)
    dDelta_s_ij = numpy.zeros([K,K], dtype=numpy.float64)
    
    for i in range(0,K):
      for j in range(0,K):
        # Compute dimensionless free energy difference and associated uncertainty (Eq. 12 of [1]).
        Delta_f_ij[i,j] = (self.f_k[j] - self.f_k[i])
        try:
          dDelta_f_ij[i,j] = math.sqrt( Theta_ij[i,i] + Theta_ij[j,j] - 2.0 * Theta_ij[i,j] )
        except:
          dDelta_f_ij[i,j] = 0.0

        # Compute reduced enthalpy difference.
        Delta_u_ij[i,j] = u_i[j] - u_i[i]
        try:
          dDelta_u_ij[i,j] = math.sqrt(
            + u_i[i] * Theta_ij[i,i]   * u_i[i] - u_i[i] * Theta_ij[i,j]   * u_i[j] - u_i[i] * Theta_ij[i,K+i]   * u_i[i] + u_i[i] * Theta_ij[i,K+j]   * u_i[j]
            - u_i[j] * Theta_ij[j,i]   * u_i[i] + u_i[j] * Theta_ij[j,j]   * u_i[j] + u_i[j] * Theta_ij[j,K+i]   * u_i[i] - u_i[j] * Theta_ij[j,K+j]   * u_i[j]
            - u_i[i] * Theta_ij[K+i,i] * u_i[i] + u_i[i] * Theta_ij[K+i,j] * u_i[j] + u_i[i] * Theta_ij[K+i,K+i] * u_i[i] - u_i[i] * Theta_ij[K+i,K+j] * u_i[j]
            + u_i[j] * Theta_ij[K+j,i] * u_i[i] - u_i[j] * Theta_ij[K+j,j] * u_i[j] - u_i[j] * Theta_ij[K+j,K+i] * u_i[i] + u_i[j] * Theta_ij[K+j,K+j] * u_i[j]
            )
        except:
          dDelta_u_ij[i,j] = 0.0

        # Compute reduced entropy difference.
        Delta_s_ij[i,j] = Delta_u_ij[i,j] - Delta_f_ij[i,j]
        try:
          dDelta_s_ij[i,j] = math.sqrt(
            +  (u_i[i]-1) * Theta_ij[i,i]   * (u_i[i]-1) +  (u_i[i]-1) * Theta_ij[i,j]   * (-u_i[j]+1) +  (u_i[i]-1) * Theta_ij[i,K+i]   * (-u_i[i]) +  (u_i[i]-1) * Theta_ij[i,K+j]   * u_i[j]
            + (-u_i[j]+1) * Theta_ij[j,i]   * (u_i[i]-1) + (-u_i[j]+1) * Theta_ij[j,j]   * (-u_i[j]+1) + (-u_i[j]+1) * Theta_ij[j,K+i]   * (-u_i[i]) + (-u_i[j]+1) * Theta_ij[j,K+j]   * u_i[j]
            + (-u_i[i])   * Theta_ij[K+i,i] * (u_i[i]-1) + (-u_i[i])   * Theta_ij[K+i,j] * (-u_i[j]+1) + (-u_i[i])   * Theta_ij[K+i,K+i] * (-u_i[i]) + (-u_i[i])   * Theta_ij[K+i,K+j] * u_i[j]
            +   u_i[j]    * Theta_ij[K+j,i] * (u_i[i]-1) +   u_i[j]    * Theta_ij[K+j,j] * (-u_i[j]+1) +   u_i[j]    * Theta_ij[K+j,K+i] * (-u_i[i]) +   u_i[j]    * Theta_ij[K+j,K+j] * u_i[j]
            )
        except:
          dDelta_s_ij[i,j] = 0.0
        
    # Return expectations and uncertainties.
    return (Delta_f_ij, dDelta_f_ij, Delta_u_ij, dDelta_u_ij, Delta_s_ij, dDelta_s_ij)
  #=============================================================================================
  def computePMF(self, u_kn, bin_kn, nbins, uncertainties='from-lowest'):
    """
    Compute the free energy of occupying a number of bins.
    This implementation computes the expectation of an indicator-function observable for each bin.

    REQUIRED ARGUMENTS
      u_kn[k,n] is the reduced potential energy of snapshot n of state k for which the PMF is to be computed.
      bin_kn[k,n] is the bin index of snapshot n of state k.  bin_kn can assume a value in range(0,nbins)
      nbins is the number of bins

    OPTIONAL ARGUMENTS
      uncertainties (string) - choose method for reporting uncertainties (default: 'from-lowest')
        'from-lowest' - the uncertainties in the free energy difference with lowest point on PMF are reported
        'from-normalization' - the normalization \sum_i p_i = 1 is used to determine uncertainties spread out through the PMF
        'all-differences' - the nbins x nbins matrix df_ij of uncertainties in free energy differences is returned instead of df_i

    RETURN VALUES
      f_i[i], i = 0..nbins - the dimensionless free energy of state i, relative to the state of lowest free energy
      df_i[i] is the uncertainty in the difference of f_i with respect to the state of lowest free energy

    NOTES
      All bins must have some samples in them from at least one of the states -- this will not work if bin_kn.sum(0) == 0. Empty bins should be removed before calling computePMF().
      This method works by computing the free energy of localizing the system to each bin for the given potential by aggregating the log weights for the given potential.
      To estimate uncertainties, the NxK weight matrix W_nk is augmented to be Nx(K+nbins) in order to accomodate the normalized weights of states where
      the potential is given by u_kn within each bin and infinite potential outside the bin.  The uncertainties with respect to the bin of lowest free energy
      are then computed in the standard way.

    WARNING
      This method is EXPERIMENTAL and should be used at your own risk.

    TEST
      
    >>> import testsystems
    >>> [x_kn, u_kln, N_k] = testsystems.HarmonicOscillatorsSample(N_k=[100,100,100])
    >>> mbar = MBAR(u_kln, N_k)
    >>> u_kn = u_kln[0,:,:]
    >>> xmin = x_kn.min()
    >>> xmax = x_kn.max()
    >>> nbins = 10
    >>> dx = (xmax - xmin) * 1.00001 / float(nbins)
    >>> bin_kn = numpy.array((x_kn - xmin) / dx, numpy.int32)
    >>> [f_i, df_i] = mbar.computePMF(u_kn, bin_kn, nbins)
    
    """

    # Verify that no PMF bins are empty -- we can't deal with empty bins, because the free energy is infinite.
    for i in range(nbins):
      if numpy.sum(bin_kn==i) == 0:
        raise ParameterError("At least one bin in provided bin_kn argument has no samples.  All bins must have samples for free energies to be finite.  Adjust bin sizes or eliminate empty bins to ensure at least one sample per bin.")
        
    K = self.K

    # Compute unnormalized log weights for the given reduced potential u_kn.
    log_w_kn = self._computeUnnormalizedLogWeights(u_kn)

    # Unroll to n-indices
    log_w_n = log_w_kn[self.indices]

    # Compute the free energies for these states.
    f_i = numpy.zeros([nbins], numpy.float64)
    df_i = numpy.zeros([nbins], numpy.float64)    
    for i in range(nbins):
      # Get linear n-indices of samples that fall in this bin.
      indices = numpy.where(bin_kn[self.indices] == i)[0]

      # Compute dimensionless free energy of occupying state i.
      f_i[i] = - logsum( log_w_n[indices] )

    # Compute uncertainties by forming matrix of W_nk.
    N_k = numpy.zeros([self.K + nbins], numpy.int32)
    N_k[0:K] = self.N_k
    W_nk = numpy.zeros([self.N, self.K + nbins], numpy.float64)
    W_nk[:,0:K] = numpy.exp(self.Log_W_nk)
    for i in range(nbins):
      # Get indices of samples that fall in this bin.
      indices = numpy.where(bin_kn[self.indices] == i)[0]
      
      # Compute normalized weights for this state.      
      W_nk[indices,K+i] = numpy.exp(log_w_n[indices] + f_i[i])

    # Compute asymptotic covariance matrix using specified method.
    Theta_ij = self._computeAsymptoticCovarianceMatrix(W_nk, N_k)

    if (uncertainties == 'from-lowest'):
      # Report uncertainties in free energy difference from lowest point on PMF.        

      # Determine bin index with lowest free energy.
      j = f_i.argmin()

      # Compute uncertainties with respect to difference in free energy from this state j.
      for i in range(nbins):
        df_i[i] = math.sqrt( Theta_ij[K+i,K+i] + Theta_ij[K+j,K+j] - 2.0 * Theta_ij[K+i,K+j] )

      # Shift free energies so that state j has zero free energy.
      f_i -= f_i[j]

      # Return dimensionless free energy and uncertainty.
      return (f_i, df_i)

    elif (uncertainties == 'all-differences'):
      # Report uncertainties in all free energy differences.
      d2f_ij = numpy.zeros([nbins,nbins], numpy.float64)    
      for i in range(nbins):
        for j in range(nbins):
          d2f_ij[i,j] = Theta_ij[K+i,K+i] + Theta_ij[K+j,K+j] - 2.0 * Theta_ij[K+i,K+j]
      # unsquare uncertainties
      df_ij = numpy.sqrt(d2f_ij)

      # Return dimensionless free energy and uncertainty.
      return (f_i, df_ij)

    elif (uncertainties == 'from-normalization'):
      # Determine uncertainties from normalization that \sum_i p_i = 1.

      # Compute bin probabilities p_i
      p_i = numpy.exp(-f_i - logsum(-f_i))

      # Compute uncertainties in bin probabilities.
      d2p_i = numpy.zeros([nbins], numpy.float64)
      for k in range(nbins):
        for i in range(nbins):
          for j in range(nbins):
            delta_ik = 1.0 * (i == k)
            delta_jk = 1.0 * (j == k)
            d2p_i[k] += p_i[k] * (p_i[i] - delta_ik) * p_i[k] * (p_i[j] - delta_jk) * Theta_ij[K+i,K+j]

      # Transform from d2p_i to df_i
      d2f_i = d2p_i / p_i**2
      df_i = numpy.sqrt(d2f_i)    

      # return free energy and uncertainty
      return (f_i, df_i)      

    else:
      raise "Uncertainty method '%s' not recognized." % uncertainties

    return
  
  #=============================================================================================
  def computePMF_states(self, u_kn, bin_kn, nbins):
    """
    Compute the free energy of occupying a number of bins.
    This implementation defines each bin as a separate thermodynamic state.

    REQUIRED ARGUMENTS
      u_kn[k,n] is the reduced potential energy of snapshot n of state k for which the PMF is to be computed.
      bin_kn[k,n] is the bin index of snapshot n of state k.  bin_kn can assume a value in range(0,nbins)
      nbins is the number of bins

    OPTIONAL ARGUMENTS
      fmax is the maximum value of the free energy, used for an empty bin (default: 1000)

    RETURN VALUES
      f_i[i], i = 0..nbins - the dimensionless free energy of state i, relative to the state of lowest free energy
      d2f_ij[i,j] is the uncertainty in the difference of (f_i - f_j)

    NOTES
      All bins must have some samples in them from at least one of the states -- this will not work if bin_kn.sum(0) == 0. Empty bins should be removed before calling computePMF().
      This method works by computing the free energy of localizing the system to each bin for the given potential by aggregating the log weights for the given potential.
      To estimate uncertainties, the NxK weight matrix W_nk is augmented to be Nx(K+nbins) in order to accomodate the normalized weights of states where
      the potential is given by u_kn within each bin and infinite potential outside the bin.  The uncertainties with respect to the bin of lowest free energy
      are then computed in the standard way.

    WARNING
      This method is EXPERIMENTAL and should be used at your own risk.
    
    """

    # Verify that no PMF bins are empty -- we can't deal with empty bins, because the free energy is infinite.
    for i in range(nbins):
      if numpy.sum(bin_kn==i) == 0:
        raise ParameterError("At least one bin in provided bin_kn argument has no samples.  All bins must have samples for free energies to be finite.  Adjust bin sizes or eliminate empty bins to ensure at least one sample per bin.")

    K = self.K
    
    # Compute unnormalized log weights for the given reduced potential u_kn.
    log_w_kn = self._computeUnnormalizedLogWeights(u_kn)
    # Unroll to n-indices
    log_w_n = log_w_kn[self.indices]

    # Compute the free energies for these states.    
    f_i = numpy.zeros([nbins], numpy.float64)
    for i in range(nbins):
      # Get linear n-indices of samples that fall in this bin.
      indices = numpy.where(bin_kn[self.indices] == i)[0]

      # Sanity check.
      if (len(indices) == 0):
        raise "WARNING: bin %d has no samples -- all bins must have at least one sample." % i

      # Compute dimensionless free energy of occupying state i.
      f_i[i] = - logsum( log_w_n[indices] )

    # Shift so that f_i.min() = 0
    f_i_min = f_i.min()
    f_i -= f_i.min()

    if self.verbose:
      print "bins f_i = "
      print f_i

    # Compute uncertainties by forming matrix of W_nk.
    if self.verbose: print "Forming W_nk matrix..."
    N_k = numpy.zeros([self.K + nbins], numpy.int32)
    N_k[0:K] = self.N_k
    W_nk = numpy.zeros([self.N, self.K + nbins], numpy.float64)
    W_nk[:,0:K] = numpy.exp(self.Log_W_nk)
    for i in range(nbins):
      # Get indices of samples that fall in this bin.
      indices = numpy.where(bin_kn[self.indices] == i)[0]

      if self.verbose: print "bin %5d count = %10d" % (i, len(indices))
      
      # Compute normalized weights for this state.      
      W_nk[indices,K+i] = numpy.exp(log_w_n[indices] + f_i[i] + f_i_min)

    # Compute asymptotic covariance matrix using specified method.
    Theta_ij = self._computeAsymptoticCovarianceMatrix(W_nk, N_k)
        
    # Compute uncertainties with respect to difference in free energy from this state j.
    d2f_ij = numpy.zeros([nbins,nbins], numpy.float64)    
    for i in range(nbins):
      for j in range(nbins):
        d2f_ij[i,j] = Theta_ij[K+i,K+i] + Theta_ij[K+j,K+j] - 2.0 * Theta_ij[K+i,K+j]

    # Return dimensionless free energy and uncertainty.
    return (f_i, d2f_ij)

  #=============================================================================================
  # PRIVATE METHODS - INTERFACES ARE NOT EXPORTED
  #=============================================================================================

  def _computeWeights(self,logform=False,include_nonzero=False, recalc_denom=True, return_f_k = False):
    """
    Compute the normalized weights corresponding to samples for the given reduced potential.
    Also stores the all_log_denom array for reuse.

    INPUT VALUES

    logform (bool): whether the output is in logarithmic form, which is better for stability, though sometimes
                    the exponential form is requires.
    include_nonzero (bool): whether to compute weights for states with nonzero states.  Not necessary 
                             when performing self-consistent iteration.
    recalc_denom (bool): recalculate the denominator, must be done if the free energies change.
                         default is to do it, so that errors are not made.  But can be turned
                         off if it is known the free energies have not changed.
    return_f_k (bool): return the self-consistent f_k values

    RETURN VALUES

    if logform==True:
      Log_W_nk (double) - Log_W_nk[n,k] is the normalized log weight of sample n from state k.
    else: 
      W_nk (double) - W_nk[n,k] is the log weight of sample n from state k.
    if return_f_k==True:
      optionally return the self-consistent free energy from these weights.

   """

    if (include_nonzero):
      f_k = self.f_k
      K = self.K
      N_k = self.N_k
    else:
      f_k = self.f_k[self.nonzero_N_k_indices]
      K = self.K_nonzero
      N_k = self.N_nonzero

    # array of either weights or normalized log weights  
    Warray_nk = numpy.zeros([self.N, K], dtype=numpy.float64)
    if (return_f_k):
      f_k_out = numpy.zeros([K],dtype=numpy.float64)

    if (recalc_denom):
      self.log_weight_denom = self._computeUnnormalizedLogWeights(numpy.zeros([self.K,self.N_max],dtype=numpy.float64))

    for l in range(K):
      # Compute log weights.
      if (include_nonzero):
        index = l
      else:
        index = self.nonzero_N_k_indices[l]
      log_w_kn = -self.u_kln[:,index,:]+ self.log_weight_denom + f_k[l]

      if (return_f_k):
        f_k_out[l] = f_k[l] - logsum( log_w_kn[self.indices] )
        if (include_nonzero):
          log_w_kn[self.indices] += (f_k_out[l]-f_k[l])  # renormalize the weights, needed for nonzero states. 

      if (logform):
        Warray_nk[:,l] = log_w_kn[self.indices]        
      else:
        Warray_nk[:,l] = numpy.exp(log_w_kn[self.indices])        

    # Return weights (or log weights)
    if (return_f_k):
      f_k_out[:] = f_k_out[:]-f_k_out[0]
      return Warray_nk,f_k_out
    else:
      return Warray_nk
      
  #=============================================================================================

  def _pseudoinverse(self, A, tol=1.0e-10):
    """
    Compute the Moore-Penrose pseudoinverse.

    REQUIRED ARGUMENTS
      A (numpy KxK matrix) - the square matrix whose pseudoinverse is to be computed

    RETURN VALUES
      Ainv (numpy KxK matrix) - the pseudoinverse

    OPTIONAL VALUES
      tol - the tolerance (relative to largest magnitude singlular value) below which singular values are to not be include in forming pseudoinverse (default: 1.0e-10)

    NOTES
      This implementation is provided because the 'pinv' function of numpy is broken in the version we were using.

    TODO
      Can we get rid of this and use numpy.linalg.pinv instead?

    """

    # DEBUG
    # TODO: Should we use pinv, or _pseudoinverse?
    #return numpy.linalg.pinv(A)

    # Get size
    [M,N] = A.shape
    if N != M:
      raise "pseudoinverse can only be computed for square matrices: dimensions were %d x %d" % (M, N)

    # Make sure A contains no nan.
    if(numpy.any(numpy.isnan(A))):
      print "attempted to compute pseudoinverse of A ="
      print A
      raise ParameterError("A contains nan.")    

    # DEBUG
    diagonal_loading = False
    if diagonal_loading:
      # Modify matrix by diagonal loading.
      eigs = numpy.linalg.eigvalsh(A)
      most_negative_eigenvalue = eigs.min()
      if (most_negative_eigenvalue < 0.0):
        print "most negative eigenvalue = %e" % most_negative_eigenvalue
        # Choose loading value.
        gamma = -most_negative_eigenvalue * 1.05
        # Modify Theta by diagonal loading
        A += gamma * numpy.eye(A.shape[0])

    # Compute SVD of A.
    [U, S, Vt] = numpy.linalg.svd(A)

    # Compute pseudoinverse by taking square root of nonzero singular values.
    Ainv = numpy.matrix(numpy.zeros([M,M], dtype=numpy.float64))
    for k in range(M):
      if (abs(S[k]) > tol * abs(S[0])):
        Ainv += (1.0/S[k]) * numpy.outer(U[:,k], Vt[k,:]).T

    return Ainv
  #=============================================================================================      
  def _zerosamestates(self, A):
    """ 
    zeros out states that should be identical 

    REQUIRED ARGUMENTS

    A: the matrix whose entries are to be zeroed.

    """

    for pair in self.samestates:
      A[pair[0],pair[1]] = 0
      A[pair[1],pair[0]] = 0
    
  #=============================================================================================      
  def _computeAsymptoticCovarianceMatrix(self, W, N_k, method=None):
    """
    Compute estimate of the asymptotic covariance matrix.
    
    REQUIRED ARGUMENTS    
      W (numpy.array of numpy.float of dimension [N,K]) - matrix of normalized weights (see Eq. 9 of [1]) - W[n,k] is the weight of snapshot n (n = 1..N) in state k
                                      Note that sum(W(:,k)) = 1 for any k = 1..K, and sum(N_k(:) .* W(n,:)) = 1 for any n.
      N_k (numpy.array of numpy.int32 of dimension [K]) - N_k[k] is the number of samples from state K

    RETURN VALUES
      Theta (KxK numpy float64 array) - asymptotic covariance matrix (see Eq. 8 of [1])

    OPTIONAL ARGUMENTS
      method (string) - if not None, specified method is used to compute asymptotic covariance method:
                        method must be one of ['generalized-inverse', 'svd', 'svd-ew', 'inverse', 'tan-HGH', 'tan', 'approximate']
                        If None is specified, 'svd-ew' is used.

    NOTES

    The computational costs of the various 'method' arguments varies:
    
      'generalized-inverse' currently requires computation of the pseudoinverse of an NxN matrix (where N is the total number of samples)
      'svd' computes the generalized inverse using the singular value decomposition -- this should be efficient yet accurate (faster)
      'svd-ev' is the same as 'svd', but uses the eigenvalue decomposition of W'W to bypass the need to perform an SVD (fastest)
      'inverse' only requires standard inversion of a KxK matrix (where K is the number of states), but requires all K states to be different
      'approximate' only requires multiplication of KxN and NxK matrices, but is an approximate underestimate of the uncertainty
      'tan' uses a simplified form that requires two pseudoinversions, but can be unstable
      'tan-HGH' makes weaker assumptions on 'tan' but can occasionally be unstable

    REFERENCE
      See Section II and Appendix D of [1].

    """  

    # Set 'svd-ew' as default if uncertainty method specified as None.
    if method == None:
      method = 'svd-ew'

    # Get dimensions of weight matrix.
    [N,K] = W.shape

    # Check dimensions
    if(K != N_k.size):
      raise ParameterError('W must be NxK, where N_k is a K-dimensional array.')      
    if(sum(N_k) != N):
      raise ParameterError('W must be NxK, where N = sum_k N_k.')
    
    # Check to make sure the weight matrix W is properly normalized.
    tolerance = 1.0e-4 # tolerance for checking equality of sums
    for k in range(0,K):
      column_sum = sum(W[:,k])
      if (abs(column_sum - 1.0) > tolerance):
        raise ParameterError('Warning: Should have \sum_n W_nk = 1.  Actual column sum for state %d was %f' % (k, column_sum))
    for n in range(0,N):
      row_sum = sum(W[n,:] * N_k)
      if (abs(row_sum - 1.0) > tolerance):
        raise ParameterError('Warning: Should have \sum_k N_k W_nk = 1.  Actual sum of row %d was %f' % (n, row_sum))      

    # Compute estimate of asymptotic covariance matrix using specified method.
    if method == 'generalized-inverse':
      # Use generalized inverse (Eq. 8 of [1]) -- most general
      # Theta = W' (I - W N W')^+ W

      # Construct matrices
      Ndiag = numpy.matrix(numpy.diag(N_k), dtype=numpy.float64) # Diagonal N_k matrix.
      W = numpy.matrix(W, dtype=numpy.float64)
      I = numpy.identity(N, dtype=numpy.float64)

      # Compute covariance
      Theta = W.T * self._pseudoinverse(I - W * Ndiag * W.T) * W      

    elif method == 'inverse':
      # Use standard inverse method (Eq. D8 of [1]) -- only applicable if all K states are different
      # Theta = [(W'W)^-1 - N + 1 1'/N]^-1
      
      # Construct matrices
      Ndiag = numpy.matrix(numpy.diag(N_k), dtype=numpy.float64) # Diagonal N_k matrix.      
      W = numpy.matrix(W, dtype=numpy.float64)
      I = numpy.identity(N, dtype=numpy.float64)
      O = numpy.ones([K,K], dtype=numpy.float64) / float(N) # matrix of ones, times 1/N

      # Make sure W is nonsingular.
      if (abs(numpy.linalg.det(W.T * W)) < tolerance):
        print "Warning: W'W appears to be singular, yet 'inverse' method of uncertainty estimation requires W contain no duplicate states."
    
      # Compute covariance
      Theta = ( (W.T * W).I - Ndiag + O).I

    elif method == 'approximate':
      # Use fast approximate expression from Kong et al. -- this underestimates the true covariance, but may be a good approximation in some cases and requires no matrix inversions
      # Theta = P'P

      # Construct matrices
      W = numpy.matrix(W, dtype=numpy.float64)

      # Compute covariance
      Theta = W.T * W

    elif method == 'svd':
      # Use singular value decomposition based approach given in supplementary material to efficiently compute uncertainty
      # See Appendix D.1, Eq. D4 in [1].

      # Construct matrices
      Ndiag = numpy.matrix(numpy.diag(N_k), dtype=numpy.float64)
      W = numpy.matrix(W, dtype=numpy.float64)
      I = numpy.identity(K, dtype=numpy.float64)      
      
      # Compute SVD of W
      [U, S, Vt] = numpy.linalg.svd(W)      
      Sigma = numpy.matrix(numpy.diag(S))
      V = numpy.matrix(Vt).T

      # Compute covariance
      Theta = V * Sigma * self._pseudoinverse(I - Sigma * V.T * Ndiag * V * Sigma) * Sigma * V.T

    elif method == 'svd-ew':
      # Use singular value decomposition based approach given in supplementary material to efficiently compute uncertainty
      # The eigenvalue decomposition of W'W is used to forego computing the SVD.
      # See Appendix D.1, Eqs. D4 and D5 of [1].

      # Construct matrices
      Ndiag = numpy.matrix(numpy.diag(N_k), dtype=numpy.float64)
      W = numpy.matrix(W, dtype=numpy.float64)
      I = numpy.identity(K, dtype=numpy.float64)      
      
      # Compute singular values and right singular vectors of W without using SVD
      # Instead, we compute eigenvalues and eigenvectors of W'W.
      # Note W'W = (U S V')'(U S V') = V S' U' U S V' = V (S'S) V'      
      [S2, V] = numpy.linalg.eigh(W.T * W)
      # Set any slightly negative eigenvalues to zero.
      S2[numpy.where(S2 < 0.0)] = 0.0
      # Form matrix of singular values Sigma, and V.
      Sigma = numpy.matrix(numpy.diag(numpy.sqrt(S2)))
      V = numpy.matrix(V)

      # Compute covariance
      Theta = V * Sigma * self._pseudoinverse(I - Sigma * V.T * Ndiag * V * Sigma) * Sigma * V.T
      
    elif method == 'tan-HGH':
      # Use method suggested by Zhiqiang Tan without further simplification.
      # TODO: There may be a problem here -- double-check this.

      [N,K] = W.shape

      # Estimate O matrix from W'W.
      W = numpy.matrix(W, dtype=numpy.float64)
      O = W.T * W

      # Assemble the Lambda matrix.
      Lambda = numpy.matrix(numpy.diag(N_k), dtype=numpy.float64)
      
      # Identity matrix.
      I = numpy.matrix(numpy.eye(K), dtype=numpy.float64)

      # Compute H and G matrices.
      H = O*Lambda - I
      G = O - O*Lambda*O
      
      # Compute pseudoinverse of H
      Hinv = self._pseudoinverse(H)

      # Compute estimate of asymptotic covariance.
      Theta = Hinv * G * Hinv.T

    elif method == 'tan':
      # Use method suggested by Zhiqiang Tan.

      # Estimate O matrix from W'W.
      W = numpy.matrix(W, dtype=numpy.float64)
      O = W.T * W

      # Assemble the Lambda matrix.
      Lambda = numpy.matrix(numpy.diag(N_k), dtype=numpy.float64)

      # Compute covariance.
      Oinv = self._pseudoinverse(O)
      Theta = self._pseudoinverse(Oinv - Lambda)

    else:
      # Raise an exception.
      raise ParameterError('Method ' + method + ' unrecognized.')
      
    return Theta
  #=============================================================================================      
  def _initializeFreeEnergies(self, verbose=False, method='zeros'):
    """
    Compute an initial guess at the relative free energies.

    OPTIONAL ARGUMENTS
      verbose (boolean) - If True, will print debug information (default: False)
      method (string) - Method for initializing guess at free energies.
        'zeros' - all free energies are initially set to zero
        'mean-reduced-potential' - the mean reduced potential is used

    """

    if (method == 'zeros'):
      # Use zeros for initial free energies.
      if verbose: print "Initializing free energies to zero."
      self.f_k[:] = 0.0
    elif (method == 'mean-reduced-potential'):
      # Compute initial guess at free energies from the mean reduced potential from each state    
      if verbose: print "Initializing free energies with mean reduced potential for each state."
      means = numpy.zeros([self.K],float)
      for k in self.nonzero_N_k_indices:
        means[k] = self.u_kln[k,k,0:self.N_k[k]].mean()
      if (numpy.max(numpy.abs(means)) < 0.000001):  
        print "Warning: All mean reduced potentials are close to zero. If you are using energy differences in the u_kln matrix, then the mean reduced potentials will be zero, and this is expected behavoir."
      self.f_k = means
    elif (method == 'BAR'):
      # TODO: Can we guess a good path for this initial guess for arbitrary "topologies"?
      # For now, make a simple list of those states with samples.
      initialization_order = numpy.where(self.N_k > 0)[0]
      # Initialize all f_k to zero.
      self.f_k[:] = 0.0
      # Initialize the rest
      for index in range(0, numpy.size(initialization_order)-1):
        k = initialization_order[index]
        l = initialization_order[index+1]
        w_F = (self.u_kln[k, l, 0:self.N_k[k]] - self.u_kln[k, k, 0:self.N_k[k]]) # forward work
        w_R = (self.u_kln[l, k, 0:self.N_k[l]] - self.u_kln[l, l, 0:self.N_k[l]]) # reverse work 

        if (len(w_F) > 0 and len(w_R) > 0): 
          # BAR solution doesn't need to be incredibly accurate to kickstart NR.
          self.f_k[l] = self.f_k[k] + BAR(w_F, w_R, relative_tolerance=0.000001, verbose=False, compute_uncertainty=False)
        else:
          # no states observed, so we don't need to initialize this free energy anyway, as 
          # the solution is noniterative.
          self.f_k[l] = 0

    else:
      # The specified method is not implemented.
      raise ParameterError('Method ' + method + ' unrecognized.')

    # Shift all free energies such that f_0 = 0.
    self.f_k[:] = self.f_k[:] - self.f_k[0]

    return 
  #=============================================================================================       
  def _computeUnnormalizedLogWeights(self, u_kn):
    """
    Return unnormalized log weights.

    REQUIRED ARGUMENTS
      u_kn (K x N_max numpy float64 array) - reduced potential energies

    OPTIONAL ARGUMENTS

    RETURN VALUES
      log_w_kn (K x N_max numpy float64 array) - unnormalized log weights

    REFERENCE
      'log weights' here refers to \log [ \sum_{k=1}^K N_k exp[f_k - (u_k(x_n) - u(x_n)] ]      
    """

    if (self.use_embedded_helper_code):	      
      # Use embedded C++ optimizations.
      import _pymbar
      u_kn = numpy.array(u_kn, dtype=numpy.float64) # necessary for helper code to interpret type of u_kn
      log_w_kn = _pymbar.computeUnnormalizedLogWeightsCpp(self.K, self.N_max, self.K_nonzero, self.nonzero_N_k_indices, self.N_k, self.f_k, self.u_kln, u_kn);
    else:
      try:
        #z= 1/0
        #pass
        from scipy import weave
        # Allocate storage for return values.
        log_w_kn = numpy.zeros([self.K,self.N_max], dtype=numpy.float64)
        # Copy useful class members to local variables.
        K = self.K
        f_k = self.f_k
        N_k = self.N_k
        u_kln = self.u_kln
        # Weave inline C++ code.
        code = """
        double log_terms[%(K)d]; // temporary storage for log terms
        for (int k = 0; k < K; k++) {
          for (int n = 0; n < N_K1(k); n++) {
            double max_log_term = 0.0;
            bool first_nonzero = true;
            for (int j = 0; j < K; j++) {
              // skip empty states
              if (N_K1(j) == 0) continue;
              double log_term = log(N_K1(j)) + F_K1(j) - U_KLN3(k,j,n) + U_KN2(k,n);
              log_terms[j] = log_term;
              if (first_nonzero || (log_term > max_log_term)) {
                max_log_term = log_term;
                first_nonzero = false;
              }
            }

            double term_sum = 0.0;
            for (int j = 0; j < K; j++) {
              // skip empty states
              if (N_K1(j) == 0) continue;
              term_sum += exp(log_terms[j] - max_log_term);
            }
            double log_term_sum = log(term_sum) + max_log_term;
            LOG_W_KN2(k,n) = - log_term_sum;
          }
        }
        """ % vars()
        # Execute inline C code with weave.
        info = weave.inline(code, ['K', 'N_k', 'u_kn', 'u_kln', 'f_k', 'log_w_kn'], headers=['<math.h>', '<stdlib.h>'], verbose=2)
      except:
        # Compute unnormalized log weights in pure Python.
        log_w_kn = numpy.zeros([self.K,self.N_max], dtype=numpy.float64)
        for k in range(0,self.K):
          for n in range(0,self.N_k[k]):
            log_w_kn[k,n] = - logsum(numpy.log(self.N_k[self.nonzero_N_k_indices]) + self.f_k[self.nonzero_N_k_indices] - (self.u_kln[k,self.nonzero_N_k_indices,n] - u_kn[k,n]) )        

    return log_w_kn


  #=============================================================================================
  def _amIdoneIterating(self,f_k_new,relative_tolerance,iteration,maximum_iterations,print_warning,verbose):
    """
    Convenience function to test whether we are done iterating, same for all iteration types 
  
    REQUIRED ARGUMENTS
      f_k_new (array): new free energies
      f_k (array) : older free energies
      relative_tolerance (float): the relative tolerance for terminating 
      verbose (bool): verbose response
      iterations (int): current number of iterations
      print_warning (bool): sometimes, we want to surpress the warning.

    RETURN VALUES
       yesIam (bool): indicates that the iteration has converged.

    """
    yesIam = False

    # Compute change from old to new estimate.
    Delta_f_k = f_k_new - self.f_k[self.nonzero_N_k_indices]

    # Check convergence criteria.
    # Terminate when max((f - fold) / f) < relative_tolerance for all nonzero f.
    max_delta = numpy.max(numpy.abs(Delta_f_k) / numpy.max(numpy.abs(f_k_new)))

    # Update stored free energies.
    f_k = f_k_new.copy()
    self.f_k[self.nonzero_N_k_indices] = f_k

    # write out current estimate
    if verbose:
      print "current f_k for states with samples ="
      print f_k
      print "relative max_delta = %e" % max_delta

    # Check convergence criteria.
    # Terminate when max((f - fold) / f) < relative_tolerance for all nonzero f.
    if numpy.isnan(max_delta) or (max_delta < relative_tolerance):
      yesIam = True
    
    if (yesIam):        
      # Report convergence, or warn user if convergence was not achieved.
      if numpy.all(self.f_k == 0.0):
        # all f_k appear to be zero
        print 'WARNING: All f_k appear to be zero.'        
      elif (max_delta < relative_tolerance):
        # Convergence achieved.
        if verbose: 
          print 'Converged to tolerance of %e in %d iterations.' % (max_delta, iteration+1)
      elif (print_warning):
        # Warn that convergence was not achieved.
        # many times, self-consistent iteration is used in conjunction with another program.  In that case, 
        # we don't really need to warn about anything, since we are not running it to convergence.
        print 'WARNING: Did not converge to within specified tolerance.'
        print 'max_delta = %e, TOLERANCE = %e, MAX_ITS = %d, iterations completed = %d' % (max_delta, relative_tolerance, maximum_iterations, iteration)

    return yesIam
  
  #=============================================================================================
  def _selfConsistentIteration(self, relative_tolerance=1.0e-6, maximum_iterations=1000, verbose=True, print_warning=False):
    """
    Determine free energies by self-consistent iteration.

    OPTIONAL ARGUMENTS

      relative_tolerance (float between 0 and 1) - relative tolerance for convergence (default 1.0e-5)
      maximum_iterations (int) - maximum number of self-consistent iterations (default 1000)
      verbose (boolean) - verbosity level for debug output

    NOTES

      Self-consistent iteration of the MBAR equations is used, as described in Appendix C.1 of [1].

    """

    # Iteratively update dimensionless free energies until convergence to specified tolerance, or maximum allowed number of iterations has been exceeded.
    if verbose: print "MBAR: Computing dimensionless free energies by iteration.  This may take from seconds to minutes, depending on the quantity of data..."
    for iteration in range(0,maximum_iterations):

      if verbose: print 'Self-consistent iteration %d' % iteration

      # compute the free energies by self consistent iteration (which also involves calculating the weights)
      (W_nk,f_k_new) = self._computeWeights(logform=True,return_f_k = True)

      if (self._amIdoneIterating(f_k_new,relative_tolerance,iteration,maximum_iterations,print_warning,verbose)): 
        break

    return

  #=============================================================================================
  def _NewtonRaphson(self, first_gamma=0.1, gamma=1.0, relative_tolerance=1.0e-6, maximum_iterations=1000, verbose=True, print_warning = True):
    """
    Determine dimensionless free energies by Newton-Raphson iteration.

    OPTIONAL ARGUMENTS
      first_gamma (float between 0 and 1) - step size multiplier to use for first step (default 0.1)
      gamma (float between 0 and 1) - step size multiplier for subsequent steps (default 1.0)
      relative_tolerance (float between 0 and 1) - relative tolerance for convergence (default 1.0e-6)
      maximum_iterations (int) - maximum number of Newton-Raphson iterations (default 1000)
      verbose (boolean) - verbosity level for debug output

    CAUTIONS
      This algorithm can sometimes cause the estimate to blow up -- we should add a check to make sure this doesn't happen, and switch
      to self-consistent iteration if it does.

    NOTES
      This method determines the dimensionless free energies by minimizing a convex function whose solution is the desired estimator.      
      The original idea came from the construction of a likelihood function that independently reproduced the work of Geyer (see [1]
      and Section 6 of [2]).
      This can alternatively be formulated as a root-finding algorithm for the Z-estimator.
      More details of this procedure will follow in a subsequent paper.
      Only those states with nonzero counts are include in the estimation procedure.
      This algorithm is expected to scale poorly with the number of states due to the inversion of the Hessian.

    REFERENCES
      See Appendix C.2 of [1].

    """

    if verbose: print "Determining dimensionless free energies by Newton-Raphson iteration."

    K = self.K_nonzero
    N_k = self.N_nonzero

    # Perform Newton-Raphson iterations
    for iteration in range(0, maximum_iterations):
      if verbose: print "Newton-Raphson iteration %d" % iteration

      # Store for new estimate of dimensionless relative free energies.
      f_k_new = self.f_k[self.nonzero_N_k_indices].copy()
      
      # compute the weights
      W_nk = self._computeWeights()  

      # Compute gradient and Hessian of last (K-1) states.
      #
      # gradient (defined by Eq. C6 of [1])
      # g_i(theta) = N_i - \sum_n N_i W_ni
      #
      # Hessian (defined by Eq. C9 of [1])
      # H_ii(theta) = - \sum_n N_i W_ni (1 - N_i W_ni)
      # H_ij(theta) = \sum_n N_i W_ni N_j W_nj
      #
      # NOTE: Calculation of the gradient and Hessian could be further optimized.

      g = numpy.matrix(numpy.zeros([K-1,1], dtype=numpy.float64)) # gradient
      H = numpy.matrix(numpy.zeros([K-1,K-1], dtype=numpy.float64)) # Hessian
      for i in range(1,K):
        g[i-1] = N_k[i] - N_k[i] * W_nk[:,i].sum()
        H[i-1,i-1] = - (N_k[i] * W_nk[:,i] * (1.0 - N_k[i] * W_nk[:,i])).sum() 
        for j in range(1,i):
          H[i-1,j-1] = (N_k[i] * W_nk[:,i] * N_k[j] * W_nk[:,j]).sum()
          H[j-1,i-1] = H[i-1,j-1]

      # Update the free energy estimate (Eq. C11 of [1]).
      Hinvg = numpy.linalg.lstsq(H,g)[0]      # solve the system of equations (may have less than full rank)
      for k in range(0,K-1):
        if iteration == 0:
          f_k_new[k+1] -= first_gamma * Hinvg[k]
        else:
          f_k_new[k+1] -= gamma * Hinvg[k]          
          
      if (self._amIdoneIterating(f_k_new,relative_tolerance,iteration,maximum_iterations,print_warning,verbose)): 
        break;

    return

  #=============================================================================================
  def _adaptive(self, gamma = 1.0, relative_tolerance=1.0e-6, maximum_iterations=1000, verbose=True, print_warning = True):
    """
    Determine dimensionless free energies by a combination of Newton-Raphson iteration and self-consistent iteration.
    Picks whichever method gives the lowest gradient.  
    Is slower than NR (approximated, not calculated) since it calculates the log norms twice each iteration.

    OPTIONAL ARGUMENTS
      gamma (float between 0 and 1) - incrementor for NR iterations.
      relative_tolerance (float between 0 and 1) - relative tolerance for convergence (default 1.0e-6)
      maximum_iterations (int) - maximum number of Newton-Raphson iterations (default 1000)
      verbose (boolean) - verbosity level for debug output

    NOTES
      This method determines the dimensionless free energies by minimizing a convex function whose solution is the desired estimator.      
      The original idea came from the construction of a likelihood function that independently reproduced the work of Geyer (see [1]
      and Section 6 of [2]).
      This can alternatively be formulated as a root-finding algorithm for the Z-estimator.
      More details of this procedure will follow in a subsequent paper.
      Only those states with nonzero counts are include in the estimation procedure.
 
    REFERENCES
      See Appendix C.2 of [1].

    """

    if verbose: print "Determining dimensionless free energies by Newton-Raphson iteration."

    # nonzero versions of variables
    K = self.K_nonzero
    N_k = self.N_nonzero

    # keep track of Newton-Raphson and self-consistent iterations
    nr_iter = 0
    sci_iter = 0

    f_k_sci = numpy.zeros([K],dtype=numpy.float64)
    f_k_new = numpy.zeros([K],dtype=numpy.float64)

    # Perform Newton-Raphson iterations (with sci computed on the way)
    for iteration in range(0, maximum_iterations):

      # Store for new estimate of dimensionless relative free energies.
      f_k = self.f_k[self.nonzero_N_k_indices].copy()

      # compute weights for gradients: the denominators and free energies are from the previous 
      # iteration in most cases.
      (W_nk,f_k_sci) = self._computeWeights(recalc_denom=(iteration==0),return_f_k = True)  

      # Compute gradient and Hessian of last (K-1) states.
      #
      # gradient (defined by Eq. C6 of [1])
      # g_i(theta) = N_i - \sum_n N_i W_ni
      #
      # Hessian (defined by Eq. C9 of [1])
      # H_ii(theta) = - \sum_n N_i W_ni (1 - N_i W_ni)
      # H_ij(theta) = \sum_n N_i W_ni N_j W_nj
      #
      # NOTE: Calculation of the gradient and Hessian could be further optimized.
      g = numpy.matrix(numpy.zeros([K-1,1], dtype=numpy.float64)) # gradient
      H = numpy.matrix(numpy.zeros([K-1,K-1], dtype=numpy.float64)) # Hessian
      for i in range(1,K):
        g[i-1] = N_k[i] - N_k[i] * W_nk[:,i].sum()
        H[i-1,i-1] = - (N_k[i] * W_nk[:,i] * (1.0 - N_k[i] * W_nk[:,i])).sum() 
        for j in range(1,i):
          H[i-1,j-1] = (N_k[i] * W_nk[:,i] * N_k[j] * W_nk[:,j]).sum()
          H[j-1,i-1] = H[i-1,j-1]

      # Update the free energy estimate (Eq. C11 of [1]).
      Hinvg = numpy.linalg.lstsq(H,g)[0]      # this would be an alterative that saves space.

      for k in range(0,K-1):
        f_k_new[k+1] = f_k[k+1] - gamma*Hinvg[k]

      # self-consistent iteration gradient norm and saved log sums.    
      g_sci = self._gradientF(f_k_sci)      
      gnorm_sci = numpy.dot(g_sci,g_sci)
      log_weight_denom = self.log_weight_denom.copy()   # save this so we can switch it back in if g_sci is lower.

      # newton raphson gradient norm and saved log sums.    
      g_nr = self._gradientF(f_k_new)
      gnorm_nr = numpy.dot(g_nr,g_nr)

      # we could save the gradient, too, but it's not too expensive to compute since we are doing the Hessian anyway.

      if verbose:
        print "self consistent iteration gradient norm is %10.5g, Newton-Raphson gradient norm is %10.5g" % (gnorm_sci, gnorm_nr)
      # decide which directon to go depending on size of gradient norm   
      if (gnorm_sci < gnorm_nr or sci_iter < 2):
        sci_iter += 1
        self.log_weight_denom = log_weight_denom.copy() 
        if verbose:
          if sci_iter < 2:
            print "Choosing self-consistent iteration on iteration %d" % iteration
          else:
            print "Choosing self-consistent iteration for lower gradient on iteration %d" % iteration
       
        f_k_new = f_k_sci.copy()
      else:
        nr_iter += 1
        if verbose: print "Newton-Raphson used on iteration %d" % iteration
      
      del(log_weight_denom) # get rid of big matrices that are not used.
  
      # have to set the free energies back in self, since the gradient routine changes them.
      self.f_k[self.nonzero_N_k_indices] = f_k
      if (self._amIdoneIterating(f_k_new,relative_tolerance,iteration,maximum_iterations,print_warning,verbose)): 
        if verbose: 
          print 'Of %d iterations, %d were Newton-Raphson iterations and %d self-consistent iterations' % (iteration+1, nr_iter, sci_iter)      
        break;

    return

  #=============================================================================================
  def _objectiveF(self,f_k):
    # this function currently not needed, but kind of interesting. The minimum variance free energy minimizes this objective function.

    f_k[0] = 0
    #gradient to solve is: g_i = N_i - N_i \sum_{n=1}^N W_{ni}
    #                          = N_i - N_i \sum_{n=1}^N exp(f_i-u_i) / \sum_{k=1} N_k exp(f_k-u_k)
    #                          = N_i - N_i \sum_{n=1}^N exp(f_i-u_i) / \sum_{k=1} N_k exp(f_k-u_k)
    # If we take F = \sum_{k=1} N_k f_k - \sum_{n=1}^N \ln [\sum_{k=1} N_k exp(f_k-u_k)] 
    # then:
    #   dF/df_i = N_i - \sum_{n=1}^N \frac{1}{\sum_{k=1} N_k exp(f_k-u_k)} d/df_i [\sum_{k=1} N_k exp(f_k-u_k)] 
    #           = N_i - \sum_{n=1}^N \frac{1}{\sum_{k=1} N_k exp(f_k-u_k)} N_i exp(f_i-u_i) 
    #           = N_i - N_i\sum_{n=1}^N \frac{exp(f_i-u_i)}{\sum_{k=1} N_k exp(f_k-u_k)} 
    #           = N_i - N_i\sum_{n=1}^N W_{ni}

    self.f_k[self.nonzero_N_k_indices] = f_k
    return -(numpy.dot(self.N_nonzero,f_k) + numpy.sum(self._computeUnnormalizedLogWeights(numpy.zeros([self.K_nonzero,self.N_max]))))

  #=============================================================================================
  def _gradientF(self,f_k):

    # take into account entries with zero samples
    self.f_k[self.nonzero_N_k_indices] = f_k
    K = self.K_nonzero
    N_k = self.N_nonzero

    W_nk = self._computeWeights(recalc_denom=True)

    g = numpy.array(numpy.zeros([K], dtype=numpy.float64)) # gradient  

    for i in range(1,K):    
      g[i] = N_k[i] - N_k[i] * W_nk[:,i].sum()      

    return g

#=============================================================================================
# MAIN AND TESTS
#=============================================================================================

if __name__ == "__main__":
  import doctest
  doctest.testmod()

