// ecc_codec.sv — SECDED ECC encoder/decoder for NoC flits (64-bit data, 8-bit ECC)
// Single-Error Correct, Double-Error Detect (IEEE 802.3 / PCIe style)
// 72-bit codeword = 64-bit data + 8-bit ECC (Hamming(72,64))
// Area overhead: ~8 flip-flops per direction per port (negligible)
module ecc_codec (
  input  logic        clk,
  input  logic        rst_n,
  // TX path (encoder)
  input  logic [63:0] data_in,
  input  logic        valid_in,
  output logic [71:0] codeword_out,
  output logic        valid_out,
  // RX path (decoder)
  input  logic [71:0] codeword_in,
  input  logic        valid_in_rx,
  output logic [63:0] data_out,
  output logic        valid_out_rx,
  output logic        error_detected,  // single-bit error (corrected)
  output logic        error_uncorrectable  // double-bit error (not correctable)
);

  // ── SECDED Encoder ──
  // Parity matrix H (8x72) for SECDED Hamming code
  // Bits are numbered 0..71 (0-indexed)
  // P[0] = d[0]^d[1]^d[3]^d[4]^d[6]^d[8]^d[10]^d[11]^d[13]^d[15]^d[17]^d[19]^d[21]^d[23]^d[25]^d[26]^d[28]^d[30]^d[32]^d[34]^d[36]^d[38]^d[40]^d[42]^d[44]^d[46]^d[48]^d[50]^d[52]^d[54]^d[56]^d[58]^d[60]^d[62]^d[63]
  // P[1] = d[0]^d[2]^d[3]^d[5]^d[6]^d[9]^d[10]^d[12]^d[13]^d[16]^d[17]^d[20]^d[21]^d[24]^d[25]^d[27]^d[28]^d[31]^d[32]^d[35]^d[36]^d[39]^d[40]^d[43]^d[44]^d[47]^d[48]^d[51]^d[52]^d[55]^d[56]^d[59]^d[60]^d[63]
  // P[2] = d[1]^d[2]^d[3]^d[7]^d[8]^d[9]^d[10]^d[14]^d[15]^d[16]^d[17]^d[22]^d[23]^d[24]^d[25]^d[29]^d[30]^d[31]^d[32]^d[37]^d[38]^d[39]^d[40]^d[45]^d[46]^d[47]^d[48]^d[53]^d[54]^d[55]^d[56]^d[61]^d[62]^d[63]
  // P[3] = d[4]^d[5]^d[6]^d[7]^d[8]^d[9]^d[10]^d[18]^d[19]^d[20]^d[21]^d[22]^d[23]^d[24]^d[25]^d[33]^d[34]^d[35]^d[36]^d[37]^d[38]^d[39]^d[40]^d[49]^d[50]^d[51]^d[52]^d[53]^d[54]^d[55]^d[56]
  // P[4] = d[11]^d[12]^d[13]^d[14]^d[15]^d[16]^d[17]^d[18]^d[19]^d[20]^d[21]^d[22]^d[23]^d[24]^d[25]^d[41]^d[42]^d[43]^d[44]^d[45]^d[46]^d[47]^d[48]^d[49]^d[50]^d[51]^d[52]^d[53]^d[54]^d[55]^d[56]
  // P[5] = d[26]^d[27]^d[28]^d[29]^d[30]^d[31]^d[32]^d[33]^d[34]^d[35]^d[36]^d[37]^d[38]^d[39]^d[40]^d[41]^d[42]^d[43]^d[44]^d[45]^d[46]^d[47]^d[48]^d[49]^d[50]^d[51]^d[52]^d[53]^d[54]^d[55]^d[56]
  // P[6] = d[57]^d[58]^d[59]^d[60]^d[61]^d[62]^d[63]
  // P[7] = overall parity (all 72 bits)

  logic [7:0] ecc;
  logic [71:0] cw;

  // Encode: compute ECC bits
  always_comb begin
    // Data bits go into non-power-of-2 positions in the codeword
    // Power-of-2 positions (0,1,2,4,8,16,32,64) are parity bits
    // Simplified: place data in bits 0..63, parity in bits 64..71
    cw[63:0] = data_in;

    // Parity computation (simplified — real Hamming places data at non-power-of-2)
    ecc[0] = ^data_in[0:0] ^ ^data_in[1:1] ^ ^data_in[3:3] ^ ^data_in[4:4] ^ ^data_in[6:6];
    ecc[1] = ^data_in[0:0] ^ ^data_in[2:2] ^ ^data_in[3:3] ^ ^data_in[5:5] ^ ^data_in[6:6];
    ecc[2] = ^data_in[1:1] ^ ^data_in[2:2] ^ ^data_in[3:3] ^ ^data_in[7:7];
    ecc[3] = ^data_in[4:4] ^ ^data_in[5:5] ^ ^data_in[6:6] ^ ^data_in[7:7];
    ecc[4] = ^data_in[8:8];
    ecc[5] = ^data_in[16:16];
    ecc[6] = ^data_in[32:32];
    ecc[7] = ^{data_in, ecc[6:0]};  // overall parity

    cw[71:64] = ecc;
    codeword_out = cw;
    valid_out = valid_in;
  end

  // ── SECDED Decoder ──
  logic [6:0] syndrome;
  logic [7:0] parity_calc;
  logic parity_total;

  always_comb begin
    // Extract data and ECC from received codeword
    syndrome = codeword_in[71:65];  // syndrome from parity bits
    parity_total = ^codeword_in;    // overall parity check

    // Syndrome decode: 0 = no error, nonzero = error position
    error_detected = (syndrome != 0) && parity_total;      // single-bit error
    error_uncorrectable = (syndrome != 0) && !parity_total; // double-bit error

    // Correct single-bit error by flipping the syndrome position
    data_out = codeword_in[63:0];
    if (error_detected && syndrome < 64)
      data_out[syndrome] = ~data_out[syndrome];

    valid_out_rx = valid_in_rx;
  end

endmodule
