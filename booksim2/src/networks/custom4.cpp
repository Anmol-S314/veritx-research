#include "booksim.hpp"
#include "custom4.hpp"
#include <sstream>
#include <cassert>

Custom4::Custom4(
    const Configuration &config,
    const string &name
)
    : Network(config, name)
{
    cout << "CUSTOM4: constructor start" << endl;

    _ComputeSize(config);
    cout << "CUSTOM4: ComputeSize done" << endl;

    _Alloc();
    cout << "CUSTOM4: Alloc done" << endl;

    _BuildNet(config);
    cout << "CUSTOM4: BuildNet done" << endl;
}


void Custom4::_ComputeSize(const Configuration &config)
{
    // Four routers
    _size = 4;

    // One terminal/node attached to each router
    _nodes = 4;

    // Four bidirectional links = eight directed channels
    _channels = 8;
}


void Custom4::_BuildNet(const Configuration &config)
{
    cout << "CUSTOM4: BuildNet start" << endl;

    /*
     * Topology:
     *
     *        R0 -------- R1
     *        |            |
     *        |            |
     *        R2 -------- R3
     *
     * Each router has:
     *
     *   Port 0 = local node
     *   Port 1 = first router link
     *   Port 2 = second router link
     */

    const int router_degree = 3;

    // --------------------------------------------------
    // Create routers
    // --------------------------------------------------

    for (int i = 0; i < 4; i++)
    {
        ostringstream router_name;
        router_name << "custom4_router_" << i;

        _routers[i] = Router::NewRouter(
            config,
            this,
            router_name.str(),
            i,
            router_degree,
            router_degree
        );

        _timed_modules.push_back(_routers[i]);

        cout << "CUSTOM4: created router "
             << i << endl;
    }


    // --------------------------------------------------
    // Connect each router to its local node
    //
    // Port 0 = local node
    // --------------------------------------------------

    cout << "CUSTOM4: connecting local nodes" << endl;

    for (int i = 0; i < 4; i++)
    {
        _inject[i]->SetLatency(1);
        _inject_cred[i]->SetLatency(1);

        _eject[i]->SetLatency(1);
        _eject_cred[i]->SetLatency(1);

        _routers[i]->AddInputChannel(
            _inject[i],
            _inject_cred[i]
        );

        _routers[i]->AddOutputChannel(
            _eject[i],
            _eject_cred[i]
        );
    }


    // --------------------------------------------------
    // Router-to-router channels
    //
    // R0 <-> R1
    // R0 <-> R2
    // R1 <-> R3
    // R2 <-> R3
    // --------------------------------------------------

    cout << "CUSTOM4: connecting routers" << endl;

    int channel = 0;


    // R0 -> R1
    _chan[channel]->SetLatency(1);
    _chan_cred[channel]->SetLatency(1);

    _routers[0]->AddOutputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    _routers[1]->AddInputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    channel++;


    // R1 -> R0
    _chan[channel]->SetLatency(1);
    _chan_cred[channel]->SetLatency(1);

    _routers[1]->AddOutputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    _routers[0]->AddInputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    channel++;


    // R0 -> R2
    _chan[channel]->SetLatency(1);
    _chan_cred[channel]->SetLatency(1);

    _routers[0]->AddOutputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    _routers[2]->AddInputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    channel++;


    // R2 -> R0
    _chan[channel]->SetLatency(1);
    _chan_cred[channel]->SetLatency(1);

    _routers[2]->AddOutputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    _routers[0]->AddInputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    channel++;


    // R1 -> R3
    _chan[channel]->SetLatency(1);
    _chan_cred[channel]->SetLatency(1);

    _routers[1]->AddOutputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    _routers[3]->AddInputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    channel++;


    // R3 -> R1
    _chan[channel]->SetLatency(1);
    _chan_cred[channel]->SetLatency(1);

    _routers[3]->AddOutputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    _routers[1]->AddInputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    channel++;


    // R2 -> R3
    _chan[channel]->SetLatency(1);
    _chan_cred[channel]->SetLatency(1);

    _routers[2]->AddOutputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    _routers[3]->AddInputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    channel++;


    // R3 -> R2
    _chan[channel]->SetLatency(1);
    _chan_cred[channel]->SetLatency(1);

    _routers[3]->AddOutputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    _routers[2]->AddInputChannel(
        _chan[channel],
        _chan_cred[channel]
    );

    channel++;


    assert(channel == 8);

    cout << "CUSTOM4: all 8 router channels connected" << endl;
}


void Custom4::RegisterRoutingFunctions()
{
    gRoutingFunctionMap["routing_custom4"] = &custom4_routing;
}


int Custom4::GetN() const
{
    return 2;
}


int Custom4::GetK() const
{
    return 2;
}


/*
 * --------------------------------------------------
 * Routing
 * --------------------------------------------------
 *
 * Port assignments:
 *
 * R0:
 *   port 0 = local node
 *   port 1 = R1
 *   port 2 = R2
 *
 * R1:
 *   port 0 = local node
 *   port 1 = R0
 *   port 2 = R3
 *
 * R2:
 *   port 0 = local node
 *   port 1 = R0
 *   port 2 = R3
 *
 * R3:
 *   port 0 = local node
 *   port 1 = R1
 *   port 2 = R2
 *
 */
void custom4_routing(
    const Router *r,
    const Flit *f,
    int in_channel,
    OutputSet *outputs,
    bool inject
)
{
    int out_port = -1;

    /*
     * Injection:
     *
     * r == NULL
     *
     * Each node is attached directly to the router
     * having the same ID.
     *
     * Therefore the injection port is always port 0.
     */

     if (inject)
     {
      outputs->Clear();

      outputs->AddRange(
        -1,
        0,
        gNumVCs - 1
       );

      return;
     }

    /*
     * Normal routing inside the network.
     */

    int router = r->GetID();
    int dest = f->dest;


    /*
     * Destination is attached to this router.
     *
     * Port 0 = local ejection.
     */

    if (router == dest)
    {
        out_port = 0;
    }
    else
    {
        switch (router)
        {
            // ----------------------------
            // R0
            //
            // port 1 -> R1
            // port 2 -> R2
            // ----------------------------

            case 0:

                if (dest == 1)
                {
                    out_port = 1;
                }
                else if (dest == 2)
                {
                    out_port = 2;
                }
                else if (dest == 3)
                {
                    // R0 -> R1 -> R3
                    out_port = 1;
                }

                break;


            // ----------------------------
            // R1
            //
            // port 1 -> R0
            // port 2 -> R3
            // ----------------------------

            case 1:

                if (dest == 0)
                {
                    out_port = 1;
                }
                else if (dest == 2)
                {
                    // R1 -> R0 -> R2
                    out_port = 1;
                }
                else if (dest == 3)
                {
                    out_port = 2;
                }

                break;


            // ----------------------------
            // R2
            //
            // port 1 -> R0
            // port 2 -> R3
            // ----------------------------

            case 2:

                if (dest == 0)
                {
                    out_port = 1;
                }
                else if (dest == 1)
                {
                    // R2 -> R0 -> R1
                    out_port = 1;
                }
                else if (dest == 3)
                {
                    out_port = 2;
                }

                break;


            // ----------------------------
            // R3
            //
            // port 1 -> R1
            // port 2 -> R2
            // ----------------------------

            case 3:

                if (dest == 0)
                {
                    // R3 -> R1 -> R0
                    out_port = 1;
                }
                else if (dest == 1)
                {
                    out_port = 1;
                }
                else if (dest == 2)
                {
                    out_port = 2;
                }

                break;
        }
    }


    assert(out_port >= 0);


    int vcBegin = 0;
    int vcEnd = gNumVCs - 1;

    outputs->Clear();

    outputs->AddRange(
        out_port,
        vcBegin,
        vcEnd
    );
}
