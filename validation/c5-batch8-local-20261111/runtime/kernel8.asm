00000000000125e0 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]>:
   125e0:	55                   	push   %rbp
   125e1:	49 89 cb             	mov    %rcx,%r11
   125e4:	48 89 e5             	mov    %rsp,%rbp
   125e7:	41 57                	push   %r15
   125e9:	41 56                	push   %r14
   125eb:	41 55                	push   %r13
   125ed:	41 54                	push   %r12
   125ef:	53                   	push   %rbx
   125f0:	48 89 fb             	mov    %rdi,%rbx
   125f3:	48 89 f7             	mov    %rsi,%rdi
   125f6:	48 89 d6             	mov    %rdx,%rsi
   125f9:	48 83 e4 e0          	and    $0xffffffffffffffe0,%rsp
   125fd:	c6 44 24 ff 00       	movb   $0x0,-0x1(%rsp)
   12602:	48 8b 47 10          	mov    0x10(%rdi),%rax
   12606:	48 8b 0f             	mov    (%rdi),%rcx
   12609:	4c 8b 67 08          	mov    0x8(%rdi),%r12
   1260d:	48 89 44 24 f0       	mov    %rax,-0x10(%rsp)
   12612:	48 8b 47 18          	mov    0x18(%rdi),%rax
   12616:	48 89 44 24 e8       	mov    %rax,-0x18(%rsp)
   1261b:	48 89 c8             	mov    %rcx,%rax
   1261e:	83 e0 03             	and    $0x3,%eax
   12621:	49 89 c6             	mov    %rax,%r14
   12624:	75 0d                	jne    12633 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x53>
   12626:	48 8d 41 01          	lea    0x1(%rcx),%rax
   1262a:	4c 39 e0             	cmp    %r12,%rax
   1262d:	0f 84 fd 02 00 00    	je     12930 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x350>
   12633:	48 8b 47 20          	mov    0x20(%rdi),%rax
   12637:	48 8b 57 28          	mov    0x28(%rdi),%rdx
   1263b:	45 31 ff             	xor    %r15d,%r15d
   1263e:	4c 8b 57 30          	mov    0x30(%rdi),%r10
   12642:	4c 8b 4f 38          	mov    0x38(%rdi),%r9
   12646:	49 89 c5             	mov    %rax,%r13
   12649:	41 83 e5 03          	and    $0x3,%r13d
   1264d:	75 0d                	jne    1265c <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x7c>
   1264f:	48 8d 78 01          	lea    0x1(%rax),%rdi
   12653:	48 39 d7             	cmp    %rdx,%rdi
   12656:	0f 84 b4 02 00 00    	je     12910 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x330>
   1265c:	48 8b 3b             	mov    (%rbx),%rdi
   1265f:	48 c1 e8 02          	shr    $0x2,%rax
   12663:	48 c1 e9 02          	shr    $0x2,%rcx
   12667:	4c 8d 04 bd 00 00 00 	lea    0x0(,%rdi,4),%r8
   1266e:	00 
   1266f:	49 0f af c0          	imul   %r8,%rax
   12673:	49 0f af c8          	imul   %r8,%rcx
   12677:	4c 01 e8             	add    %r13,%rax
   1267a:	49 89 d5             	mov    %rdx,%r13
   1267d:	83 e2 03             	and    $0x3,%edx
   12680:	49 c1 ed 02          	shr    $0x2,%r13
   12684:	4c 01 f1             	add    %r14,%rcx
   12687:	4d 0f af e8          	imul   %r8,%r13
   1268b:	4c 01 ea             	add    %r13,%rdx
   1268e:	4d 89 d5             	mov    %r10,%r13
   12691:	41 83 e2 03          	and    $0x3,%r10d
   12695:	49 c1 ed 02          	shr    $0x2,%r13
   12699:	4d 0f af e8          	imul   %r8,%r13
   1269d:	4d 01 d5             	add    %r10,%r13
   126a0:	4d 89 ca             	mov    %r9,%r10
   126a3:	41 83 e1 03          	and    $0x3,%r9d
   126a7:	49 c1 ea 02          	shr    $0x2,%r10
   126ab:	c4 c1 79 6e dd       	vmovd  %r13d,%xmm3
   126b0:	4d 0f af d0          	imul   %r8,%r10
   126b4:	4d 01 d1             	add    %r10,%r9
   126b7:	c4 c3 61 22 c1 01    	vpinsrd $0x1,%r9d,%xmm3,%xmm0
   126bd:	c5 f9 6e d8          	vmovd  %eax,%xmm3
   126c1:	c4 e3 61 22 f2 01    	vpinsrd $0x1,%edx,%xmm3,%xmm6
   126c7:	c5 c9 6c f0          	vpunpcklqdq %xmm0,%xmm6,%xmm6
   126cb:	48 85 ff             	test   %rdi,%rdi
   126ce:	0f 84 8c 02 00 00    	je     12960 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x380>
   126d4:	80 7c 24 ff 00       	cmpb   $0x0,-0x1(%rsp)
   126d9:	48 8b 53 30          	mov    0x30(%rbx),%rdx
   126dd:	c5 e0 57 db          	vxorps %xmm3,%xmm3,%xmm3
   126e1:	0f 84 99 00 00 00    	je     12780 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x1a0>
   126e7:	c5 d9 57 e4          	vxorpd %xmm4,%xmm4,%xmm4
   126eb:	c5 e2 5a 06          	vcvtss2sd (%rsi),%xmm3,%xmm0
   126ef:	c5 f8 10 14 8a       	vmovups (%rdx,%rcx,4),%xmm2
   126f4:	49 89 d0             	mov    %rdx,%r8
   126f7:	c4 e2 7d 19 c0       	vbroadcastsd %xmm0,%ymm0
   126fc:	c5 fd 28 ec          	vmovapd %ymm4,%ymm5
   12700:	45 84 ff             	test   %r15b,%r15b
   12703:	0f 84 47 01 00 00    	je     12850 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x270>
   12709:	45 31 c9             	xor    %r9d,%r9d
   1270c:	eb 16                	jmp    12724 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x144>
   1270e:	66 90                	xchg   %ax,%ax
   12710:	c4 c1 78 10 14 88    	vmovups (%r8,%rcx,4),%xmm2
   12716:	c4 a1 62 5a 04 8e    	vcvtss2sd (%rsi,%r9,4),%xmm3,%xmm0
   1271c:	4c 89 c2             	mov    %r8,%rdx
   1271f:	c4 e2 7d 19 c0       	vbroadcastsd %xmm0,%ymm0
   12724:	c5 fc 5a d2          	vcvtps2pd %xmm2,%ymm2
   12728:	c5 ed 5c d0          	vsubpd %ymm0,%ymm2,%ymm2
   1272c:	49 83 c1 01          	add    $0x1,%r9
   12730:	49 83 c0 10          	add    $0x10,%r8
   12734:	c5 fc 5a 0c 82       	vcvtps2pd (%rdx,%rax,4),%ymm1
   12739:	c5 f5 5c c0          	vsubpd %ymm0,%ymm1,%ymm0
   1273d:	c5 ed 59 d2          	vmulpd %ymm2,%ymm2,%ymm2
   12741:	c5 fd 59 c0          	vmulpd %ymm0,%ymm0,%ymm0
   12745:	c5 d5 58 ea          	vaddpd %ymm2,%ymm5,%ymm5
   12749:	c5 dd 58 e0          	vaddpd %ymm0,%ymm4,%ymm4
   1274d:	4c 39 cf             	cmp    %r9,%rdi
   12750:	75 be                	jne    12710 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x130>
   12752:	c5 fd 51 ed          	vsqrtpd %ymm5,%ymm5
   12756:	c5 fd 51 e4          	vsqrtpd %ymm4,%ymm4
   1275a:	c4 c1 7d 11 2b       	vmovupd %ymm5,(%r11)
   1275f:	c4 c1 7d 11 63 20    	vmovupd %ymm4,0x20(%r11)
   12765:	c5 f8 77             	vzeroupper
   12768:	48 8d 65 d8          	lea    -0x28(%rbp),%rsp
   1276c:	5b                   	pop    %rbx
   1276d:	41 5c                	pop    %r12
   1276f:	41 5d                	pop    %r13
   12771:	41 5e                	pop    %r14
   12773:	41 5f                	pop    %r15
   12775:	5d                   	pop    %rbp
   12776:	c3                   	ret
   12777:	66 0f 1f 84 00 00 00 	nopw   0x0(%rax,%rax,1)
   1277e:	00 00 
   12780:	4d 89 e1             	mov    %r12,%r9
   12783:	48 8b 5c 24 f0       	mov    -0x10(%rsp),%rbx
   12788:	41 83 e4 03          	and    $0x3,%r12d
   1278c:	c5 f9 6e e9          	vmovd  %ecx,%xmm5
   12790:	49 c1 e9 02          	shr    $0x2,%r9
   12794:	4d 0f af c8          	imul   %r8,%r9
   12798:	4d 01 cc             	add    %r9,%r12
   1279b:	49 89 d9             	mov    %rbx,%r9
   1279e:	83 e3 03             	and    $0x3,%ebx
   127a1:	49 c1 e9 02          	shr    $0x2,%r9
   127a5:	c4 c3 51 22 d4 01    	vpinsrd $0x1,%r12d,%xmm5,%xmm2
   127ab:	4d 0f af c8          	imul   %r8,%r9
   127af:	49 01 d9             	add    %rbx,%r9
   127b2:	48 8b 5c 24 e8       	mov    -0x18(%rsp),%rbx
   127b7:	c4 c1 79 6e e1       	vmovd  %r9d,%xmm4
   127bc:	49 89 da             	mov    %rbx,%r10
   127bf:	83 e3 03             	and    $0x3,%ebx
   127c2:	49 c1 ea 02          	shr    $0x2,%r10
   127c6:	4d 0f af d0          	imul   %r8,%r10
   127ca:	49 89 d8             	mov    %rbx,%r8
   127cd:	4d 01 d0             	add    %r10,%r8
   127d0:	c4 c3 59 22 c0 01    	vpinsrd $0x1,%r8d,%xmm4,%xmm0
   127d6:	c5 d9 57 e4          	vxorpd %xmm4,%xmm4,%xmm4
   127da:	c5 e9 6c d0          	vpunpcklqdq %xmm0,%xmm2,%xmm2
   127de:	c5 fd 28 ec          	vmovapd %ymm4,%ymm5
   127e2:	45 84 ff             	test   %r15b,%r15b
   127e5:	0f 85 c5 00 00 00    	jne    128b0 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x2d0>
   127eb:	c5 60 c2 c3 00       	vcmpeqps %xmm3,%xmm3,%xmm8
   127f0:	31 c0                	xor    %eax,%eax
   127f2:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
   127f8:	c5 78 29 c0          	vmovaps %xmm8,%xmm0
   127fc:	c4 41 78 28 c8       	vmovaps %xmm8,%xmm9
   12801:	c5 e2 5a 3c 86       	vcvtss2sd (%rsi,%rax,4),%xmm3,%xmm7
   12806:	c4 e2 7d 19 ff       	vbroadcastsd %xmm7,%ymm7
   1280b:	c4 e2 79 92 0c 92    	vgatherdps %xmm0,(%rdx,%xmm2,4),%xmm1
   12811:	48 83 c0 01          	add    $0x1,%rax
   12815:	c4 e2 31 92 04 b2    	vgatherdps %xmm9,(%rdx,%xmm6,4),%xmm0
   1281b:	48 83 c2 10          	add    $0x10,%rdx
   1281f:	c5 fc 5a c9          	vcvtps2pd %xmm1,%ymm1
   12823:	c5 fc 5a c0          	vcvtps2pd %xmm0,%ymm0
   12827:	c5 f5 5c cf          	vsubpd %ymm7,%ymm1,%ymm1
   1282b:	c5 fd 5c c7          	vsubpd %ymm7,%ymm0,%ymm0
   1282f:	c5 f5 59 c9          	vmulpd %ymm1,%ymm1,%ymm1
   12833:	c5 fd 59 c0          	vmulpd %ymm0,%ymm0,%ymm0
   12837:	c5 d5 58 e9          	vaddpd %ymm1,%ymm5,%ymm5
   1283b:	c5 dd 58 e0          	vaddpd %ymm0,%ymm4,%ymm4
   1283f:	48 39 c7             	cmp    %rax,%rdi
   12842:	75 b4                	jne    127f8 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x218>
   12844:	e9 09 ff ff ff       	jmp    12752 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x172>
   12849:	0f 1f 80 00 00 00 00 	nopl   0x0(%rax)
   12850:	c5 c0 57 ff          	vxorps %xmm7,%xmm7,%xmm7
   12854:	31 c0                	xor    %eax,%eax
   12856:	c5 c0 c2 ff 00       	vcmpeqps %xmm7,%xmm7,%xmm7
   1285b:	eb 16                	jmp    12873 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x293>
   1285d:	0f 1f 00             	nopl   (%rax)
   12860:	c4 c1 78 10 14 88    	vmovups (%r8,%rcx,4),%xmm2
   12866:	c5 e2 5a 04 86       	vcvtss2sd (%rsi,%rax,4),%xmm3,%xmm0
   1286b:	4c 89 c2             	mov    %r8,%rdx
   1286e:	c4 e2 7d 19 c0       	vbroadcastsd %xmm0,%ymm0
   12873:	c5 78 28 d7          	vmovaps %xmm7,%xmm10
   12877:	c5 fc 5a d2          	vcvtps2pd %xmm2,%ymm2
   1287b:	c5 ed 5c d0          	vsubpd %ymm0,%ymm2,%ymm2
   1287f:	48 83 c0 01          	add    $0x1,%rax
   12883:	c4 e2 29 92 0c b2    	vgatherdps %xmm10,(%rdx,%xmm6,4),%xmm1
   12889:	49 83 c0 10          	add    $0x10,%r8
   1288d:	c5 fc 5a c9          	vcvtps2pd %xmm1,%ymm1
   12891:	c5 f5 5c c0          	vsubpd %ymm0,%ymm1,%ymm0
   12895:	c5 ed 59 d2          	vmulpd %ymm2,%ymm2,%ymm2
   12899:	c5 fd 59 c0          	vmulpd %ymm0,%ymm0,%ymm0
   1289d:	c5 d5 58 ea          	vaddpd %ymm2,%ymm5,%ymm5
   128a1:	c5 dd 58 e0          	vaddpd %ymm0,%ymm4,%ymm4
   128a5:	48 39 c7             	cmp    %rax,%rdi
   128a8:	75 b6                	jne    12860 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x280>
   128aa:	e9 a3 fe ff ff       	jmp    12752 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x172>
   128af:	90                   	nop
   128b0:	c5 c0 57 ff          	vxorps %xmm7,%xmm7,%xmm7
   128b4:	31 c9                	xor    %ecx,%ecx
   128b6:	c5 c0 c2 ff 00       	vcmpeqps %xmm7,%xmm7,%xmm7
   128bb:	0f 1f 44 00 00       	nopl   0x0(%rax,%rax,1)
   128c0:	c5 f8 28 cf          	vmovaps %xmm7,%xmm1
   128c4:	c5 e2 5a 34 8e       	vcvtss2sd (%rsi,%rcx,4),%xmm3,%xmm6
   128c9:	c4 e2 7d 19 f6       	vbroadcastsd %xmm6,%ymm6
   128ce:	48 83 c1 01          	add    $0x1,%rcx
   128d2:	c4 e2 71 92 04 92    	vgatherdps %xmm1,(%rdx,%xmm2,4),%xmm0
   128d8:	c5 fc 5a 0c 82       	vcvtps2pd (%rdx,%rax,4),%ymm1
   128dd:	c5 f5 5c ce          	vsubpd %ymm6,%ymm1,%ymm1
   128e1:	48 83 c2 10          	add    $0x10,%rdx
   128e5:	c5 fc 5a c0          	vcvtps2pd %xmm0,%ymm0
   128e9:	c5 fd 5c c6          	vsubpd %ymm6,%ymm0,%ymm0
   128ed:	c5 f5 59 c9          	vmulpd %ymm1,%ymm1,%ymm1
   128f1:	c5 fd 59 c0          	vmulpd %ymm0,%ymm0,%ymm0
   128f5:	c5 dd 58 e1          	vaddpd %ymm1,%ymm4,%ymm4
   128f9:	c5 d5 58 e8          	vaddpd %ymm0,%ymm5,%ymm5
   128fd:	48 39 cf             	cmp    %rcx,%rdi
   12900:	75 be                	jne    128c0 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x2e0>
   12902:	e9 4b fe ff ff       	jmp    12752 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x172>
   12907:	66 0f 1f 84 00 00 00 	nopw   0x0(%rax,%rax,1)
   1290e:	00 00 
   12910:	48 8d 78 02          	lea    0x2(%rax),%rdi
   12914:	4c 39 d7             	cmp    %r10,%rdi
   12917:	0f 85 3f fd ff ff    	jne    1265c <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x7c>
   1291d:	48 8d 78 03          	lea    0x3(%rax),%rdi
   12921:	4c 39 cf             	cmp    %r9,%rdi
   12924:	41 0f 94 c7          	sete   %r15b
   12928:	e9 2f fd ff ff       	jmp    1265c <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x7c>
   1292d:	0f 1f 00             	nopl   (%rax)
   12930:	48 8b 54 24 f0       	mov    -0x10(%rsp),%rdx
   12935:	48 8d 41 02          	lea    0x2(%rcx),%rax
   12939:	48 39 d0             	cmp    %rdx,%rax
   1293c:	0f 85 f1 fc ff ff    	jne    12633 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x53>
   12942:	48 8b 54 24 e8       	mov    -0x18(%rsp),%rdx
   12947:	48 8d 41 03          	lea    0x3(%rcx),%rax
   1294b:	48 39 d0             	cmp    %rdx,%rax
   1294e:	0f 94 44 24 ff       	sete   -0x1(%rsp)
   12953:	e9 db fc ff ff       	jmp    12633 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x53>
   12958:	0f 1f 84 00 00 00 00 	nopl   0x0(%rax,%rax,1)
   1295f:	00 
   12960:	c5 d9 57 e4          	vxorpd %xmm4,%xmm4,%xmm4
   12964:	c5 fd 28 ec          	vmovapd %ymm4,%ymm5
   12968:	e9 e5 fd ff ff       	jmp    12752 <mvdb::exact::distances8_avx2(mvdb::exact::Compact const&, unsigned long const*, std::vector<float, std::allocator<float> > const&, double*) [clone .isra.0]+0x172>
   1296d:	90                   	nop
   1296e:	66 90                	xchg   %ax,%ax

