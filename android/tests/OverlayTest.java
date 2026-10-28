package com.dsefa.flir;
public final class OverlayTest {
    public static void main(String[] args) {
        check(OverlayModel.textColor(new int[]{0xff000000,0xff111111})==0xffffffff,"dark background needs white text");
        check(OverlayModel.textColor(new int[]{0xffffffff,0xffffeecc})==0xff000000,"bright background needs black text");
        OverlayModel h=new OverlayModel();
        h.add(1000,new double[]{22,25,Double.NaN});h.add(2000,new double[]{24,23});
        check(h.samples().size()==2&&h.samples().get(0).value==25&&h.samples().get(1).value==24,"plot must use maximum, not mean or pinned point");
        h.add(2100,new double[]{Double.NaN});check(h.samples().size()==2,"invalid frame must not invent maximum");
        h.add(33000,new double[]{26});check(h.samples().size()==1,"old history must expire");
        h.add(500,new double[]{20});check(h.samples().size()==1&&h.samples().get(0).stamp==500,"replay rewind must reset timeline");
        h.clear();check(h.samples().isEmpty(),"new stream must not connect unrelated sessions");
        check(OverlayModel.line(0,25.64).equals("P1  ·  25.6 °C"),"one compact row per pin");
        System.out.println("PASS adaptive overlay contrast / maximum history / replay rewind / pin rows");
    }
    private static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
}
