// $Id$

/*
 Copyright (c) 2007-2015, Trustees of The Leland Stanford Junior University
 All rights reserved.

 Redistribution and use in source and binary forms, with or without
 modification, are permitted provided that the following conditions are met:

 Redistributions of source code must retain the above copyright notice, this 
 list of conditions and the following disclaimer.
 Redistributions in binary form must reproduce the above copyright notice, this
 list of conditions and the following disclaimer in the documentation and/or
 other materials provided with the distribution.

 THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
 ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE 
 DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
 ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
 ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
*/

/*stats.cpp
 *
 *class stores statistics gnerated by the trafficmanager such as the latency
 *hope count of the the flits
 *
 *reset option resets the min and max alues of this statistiscs
 */

#include "booksim.hpp"
#include <iostream>
#include <sstream>
#include <limits>
#include <cmath>
#include <cstdio>

#include "stats.hpp"

Stats::Stats( Module *parent, const string &name,
	      double bin_size, int num_bins ) :
  Module( parent, name ), _num_bins( num_bins ), _bin_size( bin_size )
{
  Clear();
}

void Stats::Clear( )
{
  _num_samples = 0;
  _sample_sum  = 0.0;
  _sample_squared_sum = 0.0;

  _hist.assign(_num_bins, 0);

  _min = numeric_limits<double>::quiet_NaN();
  _max = -numeric_limits<double>::quiet_NaN();
  
  //  _reset = true;
}

double Stats::Average( ) const
{
  return _sample_sum / (double)_num_samples;
}

double Stats::Variance( ) const
{
  return (_sample_squared_sum * (double)_num_samples - _sample_sum * _sample_sum) / ((double)_num_samples * (double)_num_samples);
}

double Stats::Min( ) const
{
  return _min;
}

double Stats::Max( ) const
{
  return _max;
}

double Stats::Sum( ) const
{
  return _sample_sum;
}

double Stats::SquaredSum( ) const
{
  return _sample_squared_sum;
}

int Stats::NumSamples( ) const
{
  return _num_samples;
}

void Stats::AddSample( double val )
{
  ++_num_samples;
  _sample_sum += val;

  // NOTE: the negation ensures that NaN values are handled correctly!
  _max = !(val <= _max) ? val : _max;
  _min = !(val >= _min) ? val : _min;

  // VeritX: log-linear binning for wide dynamic range
  // bins 0-99: linear 0-1000 (10 per unit)
  // bins 100+: log-scale 1K to 10^(n-99)
  int b;
  if (val <= 0) {
    b = 0;
  } else if (val < 1000) {
    b = (int)(val / 10.0);  // 10 bins per unit, 0-999
  } else {
    b = 100 + (int)std::ceil(std::log10(val / 1000.0));
    if (b >= _num_bins) b = _num_bins - 1;
  }

  _hist[b]++;
}

void Stats::Display( ostream & os ) const
{
  os << *this << endl;
}

ostream & operator<<(ostream & os, const Stats & s) {
  vector<int> const & v = s._hist;
  os << "[ ";
  for(size_t i = 0; i < v.size(); ++i) {
    os << v[i] << " ";
  }
  os << "]";
  return os;
}

// VeritX: percentile computation from histogram
// Uses log-linear bins: 0-999 linear, 1000+ log-scale
double Stats::Percentile(double p) const {
  if (_num_samples == 0) return 0.0;
  int target = (int)(p / 100.0 * _num_samples);
  int cumulative = 0;
  for (int b = 0; b < _num_bins; ++b) {
    cumulative += _hist[b];
    if (cumulative >= target) {
      // Convert bin index to actual value
      if (b < 100) {
        return b * 10.0 + 5.0;  // center of linear bin
      } else {
        return std::pow(10.0, (b - 100) + 3);  // log-scale: 10^(b-97)
      }
    }
  }
  return std::pow(10.0, (_num_bins - 100) + 3);  // last bin
}
