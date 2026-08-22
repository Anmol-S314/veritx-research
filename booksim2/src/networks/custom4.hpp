#ifndef _CUSTOM4_HPP_
#define _CUSTOM4_HPP_

#include "network.hpp"
#include "routefunc.hpp"

class Custom4 : public Network
{
public:
    Custom4(const Configuration &config, const string &name);

    int GetN() const;
    int GetK() const;

    static void RegisterRoutingFunctions();

private:
    void _ComputeSize(const Configuration &config);
    void _BuildNet(const Configuration &config);
};

void custom4_routing(
    const Router *r,
    const Flit *f,
    int in_channel,
    OutputSet *outputs,
    bool inject
);

#endif
