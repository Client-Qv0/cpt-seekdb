00000000000124f0 <mvdb::exact::distances8_contiguous_avx2(mvdb::exact::Compact const&, unsigned long, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]>:
   124f0:	4c 8b 07             	mov    (%rdi),%r8
   124f3:	48 89 f0             	mov    %rsi,%rax
   124f6:	49 89 d1             	mov    %rdx,%r9
   124f9:	48 c1 e8 02          	shr    $0x2,%rax
   124fd:	49 0f af c0          	imul   %r8,%rax
   12501:	48 c1 e0 04          	shl    $0x4,%rax
   12505:	48 03 47 30          	add    0x30(%rdi),%rax
   12509:	4d 85 c0             	test   %r8,%r8
   1250c:	74 72                	je     12580 <mvdb::exact::distances8_contiguous_avx2(mvdb::exact::Compact const&, unsigned long, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x90>
   1250e:	4c 89 c6             	mov    %r8,%rsi
   12511:	c5 e1 57 db          	vxorpd %xmm3,%xmm3,%xmm3
   12515:	c5 d0 57 ed          	vxorps %xmm5,%xmm5,%xmm5
   12519:	31 d2                	xor    %edx,%edx
   1251b:	48 c1 e6 04          	shl    $0x4,%rsi
   1251f:	c5 fd 28 e3          	vmovapd %ymm3,%ymm4
   12523:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
   12528:	c4 c1 52 5a 14 91    	vcvtss2sd (%r9,%rdx,4),%xmm5,%xmm2
   1252e:	c5 fc 5a 08          	vcvtps2pd (%rax),%ymm1
   12532:	48 83 c2 01          	add    $0x1,%rdx
   12536:	48 83 c0 10          	add    $0x10,%rax
   1253a:	c4 e2 7d 19 d2       	vbroadcastsd %xmm2,%ymm2
   1253f:	c5 fc 5a 44 30 f0    	vcvtps2pd -0x10(%rax,%rsi,1),%ymm0
   12545:	c5 f5 5c ca          	vsubpd %ymm2,%ymm1,%ymm1
   12549:	c5 fd 5c c2          	vsubpd %ymm2,%ymm0,%ymm0
   1254d:	c5 f5 59 c9          	vmulpd %ymm1,%ymm1,%ymm1
   12551:	c5 fd 59 c0          	vmulpd %ymm0,%ymm0,%ymm0
   12555:	c5 dd 58 e1          	vaddpd %ymm1,%ymm4,%ymm4
   12559:	c5 e5 58 d8          	vaddpd %ymm0,%ymm3,%ymm3
   1255d:	49 39 d0             	cmp    %rdx,%r8
   12560:	75 c6                	jne    12528 <mvdb::exact::distances8_contiguous_avx2(mvdb::exact::Compact const&, unsigned long, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x38>
   12562:	c5 fd 51 e4          	vsqrtpd %ymm4,%ymm4
   12566:	c5 fd 51 db          	vsqrtpd %ymm3,%ymm3
   1256a:	c5 fd 11 21          	vmovupd %ymm4,(%rcx)
   1256e:	c5 fd 11 59 20       	vmovupd %ymm3,0x20(%rcx)
   12573:	c5 f8 77             	vzeroupper
   12576:	c3                   	ret
   12577:	66 0f 1f 84 00 00 00 	nopw   0x0(%rax,%rax,1)
   1257e:	00 00 
   12580:	c5 e1 57 db          	vxorpd %xmm3,%xmm3,%xmm3
   12584:	c5 fd 28 e3          	vmovapd %ymm3,%ymm4
   12588:	eb d8                	jmp    12562 <mvdb::exact::distances8_contiguous_avx2(mvdb::exact::Compact const&, unsigned long, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x72>
   1258a:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)

