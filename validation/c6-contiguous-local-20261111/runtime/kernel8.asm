00000000000123e0 <mvdb::exact::distances8_contiguous_avx2(mvdb::exact::Compact const&, unsigned long, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]>:
   123e0:	4c 8b 07             	mov    (%rdi),%r8
   123e3:	48 89 f0             	mov    %rsi,%rax
   123e6:	49 89 d1             	mov    %rdx,%r9
   123e9:	48 c1 e8 02          	shr    $0x2,%rax
   123ed:	49 0f af c0          	imul   %r8,%rax
   123f1:	48 c1 e0 04          	shl    $0x4,%rax
   123f5:	48 03 47 30          	add    0x30(%rdi),%rax
   123f9:	4d 85 c0             	test   %r8,%r8
   123fc:	74 72                	je     12470 <mvdb::exact::distances8_contiguous_avx2(mvdb::exact::Compact const&, unsigned long, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x90>
   123fe:	4c 89 c6             	mov    %r8,%rsi
   12401:	c5 e1 57 db          	vxorpd %xmm3,%xmm3,%xmm3
   12405:	c5 d0 57 ed          	vxorps %xmm5,%xmm5,%xmm5
   12409:	31 d2                	xor    %edx,%edx
   1240b:	48 c1 e6 04          	shl    $0x4,%rsi
   1240f:	c5 fd 28 e3          	vmovapd %ymm3,%ymm4
   12413:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
   12418:	c4 c1 52 5a 14 91    	vcvtss2sd (%r9,%rdx,4),%xmm5,%xmm2
   1241e:	c5 fc 5a 08          	vcvtps2pd (%rax),%ymm1
   12422:	48 83 c2 01          	add    $0x1,%rdx
   12426:	48 83 c0 10          	add    $0x10,%rax
   1242a:	c4 e2 7d 19 d2       	vbroadcastsd %xmm2,%ymm2
   1242f:	c5 fc 5a 44 30 f0    	vcvtps2pd -0x10(%rax,%rsi,1),%ymm0
   12435:	c5 f5 5c ca          	vsubpd %ymm2,%ymm1,%ymm1
   12439:	c5 fd 5c c2          	vsubpd %ymm2,%ymm0,%ymm0
   1243d:	c5 f5 59 c9          	vmulpd %ymm1,%ymm1,%ymm1
   12441:	c5 fd 59 c0          	vmulpd %ymm0,%ymm0,%ymm0
   12445:	c5 dd 58 e1          	vaddpd %ymm1,%ymm4,%ymm4
   12449:	c5 e5 58 d8          	vaddpd %ymm0,%ymm3,%ymm3
   1244d:	49 39 d0             	cmp    %rdx,%r8
   12450:	75 c6                	jne    12418 <mvdb::exact::distances8_contiguous_avx2(mvdb::exact::Compact const&, unsigned long, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x38>
   12452:	c5 fd 51 e4          	vsqrtpd %ymm4,%ymm4
   12456:	c5 fd 51 db          	vsqrtpd %ymm3,%ymm3
   1245a:	c5 fd 11 21          	vmovupd %ymm4,(%rcx)
   1245e:	c5 fd 11 59 20       	vmovupd %ymm3,0x20(%rcx)
   12463:	c5 f8 77             	vzeroupper
   12466:	c3                   	ret
   12467:	66 0f 1f 84 00 00 00 	nopw   0x0(%rax,%rax,1)
   1246e:	00 00 
   12470:	c5 e1 57 db          	vxorpd %xmm3,%xmm3,%xmm3
   12474:	c5 fd 28 e3          	vmovapd %ymm3,%ymm4
   12478:	eb d8                	jmp    12452 <mvdb::exact::distances8_contiguous_avx2(mvdb::exact::Compact const&, unsigned long, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x72>
   1247a:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)

