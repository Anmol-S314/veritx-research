// Synchronous FIFO with formal properties
module fifo #(
    parameter DEPTH = 4,
    parameter WIDTH = 8
)(
    input  logic             clk,
    input  logic             rst_n,
    input  logic             wr_en,
    input  logic [WIDTH-1:0] wr_data,
    input  logic             rd_en,
    output logic [WIDTH-1:0] rd_data,
    output logic             full,
    output logic             empty
);
    logic [$clog2(DEPTH):0] wr_ptr, rd_ptr;   // extra MSB distinguishes full from empty
    logic [WIDTH-1:0] mem [0:DEPTH-1];

    assign full  = (wr_ptr[$clog2(DEPTH)] != rd_ptr[$clog2(DEPTH)]) &&
                   (wr_ptr[$clog2(DEPTH)-1:0] == rd_ptr[$clog2(DEPTH)-1:0]);
    assign empty = (wr_ptr == rd_ptr);

    // known formal start state
    initial begin
        wr_ptr = '0;
        rd_ptr = '0;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= '0;
            rd_ptr <= '0;
        end else begin
            if (wr_en && !full) begin
                mem[wr_ptr[$clog2(DEPTH)-1:0]] <= wr_data;
                wr_ptr <= wr_ptr + 1;
            end
            if (rd_en && !empty) begin
                rd_data <= mem[rd_ptr[$clog2(DEPTH)-1:0]];
                rd_ptr <= rd_ptr + 1;
            end
        end
    end

    wire [$clog2(DEPTH):0] occupancy = wr_ptr - rd_ptr;

    always_comb assert(occupancy <= DEPTH);   // no overflow/underflow
    always_comb assert(!(full && empty));
endmodule
